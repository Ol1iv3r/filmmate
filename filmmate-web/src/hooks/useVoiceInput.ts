/**
 * Phase 2：录音状态机。
 *
 *   idle -> requesting -> recording -> transcribing -> idle
 *
 * 职责：
 * - 持有 MediaStream / MediaRecorder，任何退出路径都释放麦克风
 * - 限制最短 / 最长录音时长
 * - 把音频交给 transcribeAudio()，把文字交回给调用方
 *
 * 组件只负责「把文字放进输入框」，本 hook 不碰草稿、不自动发送。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { formatDuration, isRecordingSupported, pickAudioMimeType } from '../lib/voiceInput'
import { transcribeAudio } from '../lib/voiceInputApi'

export type VoiceInputStatus = 'idle' | 'requesting' | 'recording' | 'transcribing'

export interface UseVoiceInputOptions {
  /** 到点自动停止。whisper-1 上限 25 MB，32 kbps 约 90 分钟。 */
  maxDurationMs?: number
  /** 低于这个时长的录音当作误触。 */
  minDurationMs?: number
  onTranscript?: (text: string) => void
}

export interface VoiceInput {
  status: VoiceInputStatus
  elapsedMs: number
  error: string | null
  supported: boolean
  start: () => Promise<void>
  stop: () => Promise<string | null>
  cancel: () => void
  clearError: () => void
}

const MIN_AUDIO_BYTES = 512

export function useVoiceInput({
  maxDurationMs = 120_000,
  minDurationMs = 400,
  onTranscript,
}: UseVoiceInputOptions = {}): VoiceInput {
  const [status, setStatus] = useState<VoiceInputStatus>('idle')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const statusRef = useRef<VoiceInputStatus>('idle')
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startedAtRef = useRef(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelRef = useRef(false)
  const resolveStopRef = useRef<((text: string | null) => void) | null>(null)
  const durationRef = useRef(0)
  const onTranscriptRef = useRef(onTranscript)

  onTranscriptRef.current = onTranscript
  statusRef.current = status

  const clearTick = useCallback(() => {
    if (tickRef.current !== null) {
      clearInterval(tickRef.current)
      tickRef.current = null
    }
  }, [])

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    recorderRef.current = null
  }, [])

  const finish = useCallback(
    async (blob: Blob) => {
      const resolve = resolveStopRef.current
      resolveStopRef.current = null

      if (cancelRef.current) {
        setStatus('idle')
        setElapsedMs(0)
        resolve?.(null)
        return
      }

      if (blob.size < MIN_AUDIO_BYTES || durationRef.current < minDurationMs) {
        setError('录音太短，请再试一次。')
        setStatus('idle')
        setElapsedMs(0)
        resolve?.(null)
        return
      }

      setStatus('transcribing')
      try {
        const result = await transcribeAudio(blob)
        if (!result.ok) {
          setError(result.message)
          resolve?.(null)
          return
        }

        setError(null)
        onTranscriptRef.current?.(result.text)
        resolve?.(result.text)
      } catch (unknownError) {
        setError(`转写失败：${(unknownError as Error).message}`)
        resolve?.(null)
      } finally {
        setStatus('idle')
        setElapsedMs(0)
      }
    },
    [minDurationMs],
  )

  const start = useCallback(async () => {
    if (statusRef.current !== 'idle') return
    if (!isRecordingSupported()) {
      setError('当前环境不支持录音。')
      return
    }

    cancelRef.current = false
    setError(null)
    setStatus('requesting')

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch (unknownError) {
      const name = (unknownError as Error).name
      setError(
        name === 'NotAllowedError'
          ? '麦克风权限被拒绝，请在系统设置中允许本应用使用麦克风。'
          : name === 'NotFoundError'
            ? '找不到麦克风设备。'
            : `无法打开麦克风：${(unknownError as Error).message}`,
      )
      setStatus('idle')
      return
    }

    // 权限弹窗期间用户已经取消。
    if (cancelRef.current) {
      stream.getTracks().forEach((track) => track.stop())
      setStatus('idle')
      return
    }

    streamRef.current = stream
    const mimeType = pickAudioMimeType()

    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType, audioBitsPerSecond: 32_000 } : undefined,
      )
    } catch (unknownError) {
      stream.getTracks().forEach((track) => track.stop())
      setError(`无法初始化录音器：${(unknownError as Error).message}`)
      setStatus('idle')
      return
    }

    recorderRef.current = recorder
    chunksRef.current = []
    startedAtRef.current = Date.now()

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data)
    }
    recorder.onstop = () => {
      clearTick()
      releaseStream()
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      chunksRef.current = []
      void finish(blob)
    }
    recorder.onerror = (event) => {
      const message = (event as unknown as { error?: Error }).error?.message ?? '未知错误'
      setError(`录音中断：${message}`)
    }

    recorder.start(250)
    setStatus('recording')

    tickRef.current = setInterval(() => {
      const elapsed = Date.now() - startedAtRef.current
      setElapsedMs(elapsed)
      if (elapsed >= maxDurationMs) {
        clearTick()
        void stopRef.current()
      }
    }, 200)
  }, [clearTick, finish, maxDurationMs, releaseStream])

  const stop = useCallback((): Promise<string | null> => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return Promise.resolve(null)

    durationRef.current = Date.now() - startedAtRef.current

    return new Promise<string | null>((resolve) => {
      resolveStopRef.current = resolve
      try {
        recorder.stop()
      } catch {
        clearTick()
        releaseStream()
        setStatus('idle')
        setElapsedMs(0)
        resolve(null)
      }
    })
  }, [clearTick, releaseStream])

  const stopRef = useRef(stop)
  stopRef.current = stop

  const cancel = useCallback(() => {
    cancelRef.current = true
    clearTick()
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop()
        return
      } catch {
        /* 落到下面的硬重置 */
      }
    }
    releaseStream()
    setStatus('idle')
    setElapsedMs(0)
  }, [clearTick, releaseStream])

  // Esc 取消当前录音（与 Electron 版一致）。
  useEffect(() => {
    if (status !== 'recording') return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        cancel()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [cancel, status])

  // 组件卸载时释放麦克风与定时器。
  useEffect(() => {
    return () => {
      cancelRef.current = true
      if (tickRef.current !== null) clearInterval(tickRef.current)
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop()
        } catch {
          /* ignore */
        }
      }
      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  return {
    status,
    elapsedMs,
    error,
    supported: isRecordingSupported(),
    start,
    stop,
    cancel,
    clearError: () => setError(null),
  }
}
