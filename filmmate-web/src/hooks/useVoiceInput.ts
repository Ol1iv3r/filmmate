/**
 * Phase 2：录音状态机 + 浏览器语音识别兜底。
 *
 *   idle -> requesting -> recording -> transcribing -> idle
 *
 * 首选服务端 whisper（POST /api/transcribe）；当服务端额度用尽（402）或未配置密钥时，
 * 自动切换到浏览器原生 SpeechRecognition（Chrome / Edge 可用），不需要任何 API Key。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { isRecordingSupported, pickAudioMimeType } from '../lib/voiceInput'
import { getTranscribeStatus, transcribeAudio } from '../lib/voiceInputApi'

export type VoiceInputStatus = 'idle' | 'requesting' | 'recording' | 'transcribing'
export type VoiceInputEngine = 'server' | 'browser'

export interface UseVoiceInputOptions {
  maxDurationMs?: number
  minDurationMs?: number
  onTranscript?: (text: string) => void
}

export interface VoiceInput {
  status: VoiceInputStatus
  elapsedMs: number
  error: string | null
  supported: boolean
  engine: VoiceInputEngine
  start: () => Promise<void>
  stop: () => Promise<string | null>
  cancel: () => void
  clearError: () => void
}

const MIN_AUDIO_BYTES = 512
const ENGINE_KEY = 'filmmate.voice.engine'

type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
}

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null
  const w = window as any
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

function browserSRAvailable(): boolean {
  return !!getSpeechRecognition()
}

function rememberEngine(engine: VoiceInputEngine) {
  try {
    window.localStorage.setItem(ENGINE_KEY, engine)
  } catch {
    /* localStorage 不可用就忽略 */
  }
}

export function useVoiceInput({
  maxDurationMs = 120_000,
  minDurationMs = 400,
  onTranscript,
}: UseVoiceInputOptions = {}): VoiceInput {
  const [status, setStatus] = useState<VoiceInputStatus>('idle')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [engine, setEngine] = useState<VoiceInputEngine>('server')

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
  const browserModeRef = useRef(false)
  const srRef = useRef<SpeechRecognitionLike | null>(null)
  const srTextRef = useRef('')
  const srResolveRef = useRef<((text: string | null) => void) | null>(null)

  onTranscriptRef.current = onTranscript
  statusRef.current = status

  // 初始化：记忆上次切换结果；服务端未配置转写时直接用浏览器识别
  useEffect(() => {
    let remembered = ''
    try {
      remembered = window.localStorage.getItem(ENGINE_KEY) || ''
    } catch {
      /* ignore */
    }
    if (remembered === 'browser' && browserSRAvailable()) {
      browserModeRef.current = true
      setEngine('browser')
    }
    let cancelled = false
    void getTranscribeStatus().then((info) => {
      if (cancelled) return
      if (!info.configured && browserSRAvailable()) {
        browserModeRef.current = true
        setEngine('browser')
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

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

  const switchToBrowser = useCallback((reason: string) => {
    if (!browserSRAvailable()) return
    browserModeRef.current = true
    setEngine('browser')
    rememberEngine('browser')
    setError(reason + ' 已切换到浏览器语音识别（Chrome/Edge），请再点一次麦克风。')
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
          if (result.code === 'QUOTA') {
            switchToBrowser(result.message)
          } else {
            setError(result.message)
          }
          resolve?.(null)
          return
        }

        setError(null)
        onTranscriptRef.current?.(result.text)
        resolve?.(result.text)
      } catch (unknownError) {
        setError('转写失败：' + (unknownError as Error).message)
        resolve?.(null)
      } finally {
        setStatus('idle')
        setElapsedMs(0)
      }
    },
    [minDurationMs, switchToBrowser],
  )

  const startBrowser = useCallback(() => {
    const SR = getSpeechRecognition()
    if (!SR) {
      setError('当前浏览器不支持语音识别，建议用 Chrome / Edge。')
      setStatus('idle')
      return
    }
    setError(null)
    setStatus('requesting')
    let rec: SpeechRecognitionLike
    try {
      rec = new SR()
    } catch (unknownError) {
      setError('无法启动浏览器语音识别：' + (unknownError as Error).message)
      setStatus('idle')
      return
    }
    srRef.current = rec
    srTextRef.current = ''
    rec.lang = 'zh-CN'
    rec.continuous = false
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (event: any) => {
      try {
        let text = ''
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const item = event.results[i]
          text += item[0]?.transcript ?? ''
        }
        srTextRef.current = (srTextRef.current + text).trim()
      } catch {
        /* ignore */
      }
    }
    rec.onerror = (event: any) => {
      const code = String(event?.error ?? 'unknown')
      if (code === 'aborted') return
      clearTick()
      setStatus('idle')
      setElapsedMs(0)
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        setError('浏览器麦克风权限被拒绝，请在浏览器设置里允许本站使用麦克风。')
      } else if (code === 'no-speech') {
        setError('没有听到声音，请再试一次。')
      } else {
        setError('浏览器语音识别失败：' + code)
      }
      const resolve = srResolveRef.current
      srResolveRef.current = null
      resolve?.(null)
    }
    rec.onend = () => {
      clearTick()
      srRef.current = null
      setStatus('idle')
      setElapsedMs(0)
      const text = (srTextRef.current || '').trim()
      const resolve = srResolveRef.current
      srResolveRef.current = null
      if (text) {
        setError(null)
        onTranscriptRef.current?.(text)
        resolve?.(text)
      } else {
        if (!cancelRef.current) setError('没有识别出文字，请再试一次。')
        resolve?.(null)
      }
    }
    startedAtRef.current = Date.now()
    tickRef.current = setInterval(() => {
      const elapsed = Date.now() - startedAtRef.current
      setElapsedMs(elapsed)
      if (elapsed >= maxDurationMs) {
        clearTick()
        try {
          rec.stop()
        } catch {
          /* ignore */
        }
      }
    }, 200)
    try {
      rec.start()
    } catch (unknownError) {
      clearTick()
      setStatus('idle')
      setError('无法启动浏览器语音识别：' + (unknownError as Error).message)
      return
    }
    setStatus('recording')
  }, [clearTick, maxDurationMs])

  const start = useCallback(async () => {
    if (statusRef.current !== 'idle') return

    if (browserModeRef.current && browserSRAvailable()) {
      startBrowser()
      return
    }
    if (!isRecordingSupported()) {
      if (browserSRAvailable()) {
        browserModeRef.current = true
        setEngine('browser')
        rememberEngine('browser')
        startBrowser()
        return
      }
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
            : '无法打开麦克风：' + (unknownError as Error).message,
      )
      setStatus('idle')
      return
    }

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
      setError('无法初始化录音器：' + (unknownError as Error).message)
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
      setError('录音中断：' + message)
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
  }, [clearTick, finish, maxDurationMs, releaseStream, startBrowser])

  const stop = useCallback((): Promise<string | null> => {
    const sr = srRef.current
    if (sr) {
      durationRef.current = Date.now() - startedAtRef.current
      return new Promise<string | null>((resolve) => {
        srResolveRef.current = resolve
        try {
          sr.stop()
        } catch {
          clearTick()
          srRef.current = null
          setStatus('idle')
          setElapsedMs(0)
          resolve(null)
        }
      })
    }

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
    const sr = srRef.current
    if (sr) {
      try {
        sr.abort()
      } catch {
        /* ignore */
      }
      srRef.current = null
      setStatus('idle')
      setElapsedMs(0)
      return
    }
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

  // Esc 取消当前录音。
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
      try {
        srRef.current?.abort()
      } catch {
        /* ignore */
      }
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
    supported: isRecordingSupported() || browserSRAvailable(),
    engine,
    start,
    stop,
    cancel,
    clearError: () => setError(null),
  }
}
