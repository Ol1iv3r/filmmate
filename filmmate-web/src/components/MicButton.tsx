import { useEffect, useRef, useState } from 'react'
import { Mic, MicOff } from 'lucide-react'
import { cn } from '../lib/utils'

type MicState = 'idle' | 'recording' | 'processing' | 'unsupported'

/**
 * 麦克风按钮占位（Phase 2 Jacky 接 whisper-1）。
 * 现在：按钮 + “录音中/inflight”状态可视化，不真正采集音频。
 * 接入时只需替换 handleClick 里的实现。
 */
export function MicButton() {
  const [state, setState] = useState<MicState>('idle')
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (!('SpeechRecognition' in window) && !('webkitSpeechRecognition' in window)) {
      setState('unsupported')
    }
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [])

  const toggle = () => {
    if (state === 'idle') {
      setState('recording')
      // 占位：2.5 秒后自动进入 inflight，模拟一次识别流程
      timer.current = window.setTimeout(() => {
        setState('processing')
        timer.current = window.setTimeout(() => setState('idle'), 1200)
      }, 2500)
    } else if (state === 'recording') {
      if (timer.current) window.clearTimeout(timer.current)
      setState('idle')
    }
  }

  const labels: Record<MicState, string> = {
    idle: '语音输入（Phase 2 接入 whisper-1）',
    recording: '录音中… 点击停止',
    processing: '转写中…',
    unsupported: '当前浏览器不支持语音识别',
  }

  return (
    <button
      type="button"
      className={cn('mic-btn', state !== 'idle' && state !== 'unsupported' && 'active', state === 'recording' && 'recording')}
      onClick={toggle}
      title={labels[state]}
      aria-label={labels[state]}
    >
      {state === 'unsupported' ? <MicOff size={17} /> : <Mic size={17} />}
      {state === 'recording' && <span className="mic-ring" aria-hidden />}
      {state === 'processing' && <span className="mic-spinner" aria-hidden />}
    </button>
  )
}
