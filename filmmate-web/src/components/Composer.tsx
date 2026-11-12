import { forwardRef, useImperativeHandle, useRef, type KeyboardEvent, type FormEvent } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import { cn } from '../lib/utils'
import { MicButton } from './MicButton'

export interface ComposerHandle {
  /** 一键填入文本并聚焦（空态示例卡用）。 */
  fill: (text: string) => void
  focus: () => void
}

interface ComposerProps {
  value: string
  onChange: (text: string) => void
  streaming: boolean
  onSend: (text: string) => void
  onStop: () => void
  placeholder?: string
}

/**
 * 输入区：多行、Enter 发送 / Shift+Enter 换行、中文输入法保护、
 * 流式中自动变停止按钮、自动增高。受控组件（空态示例卡一键填入）。
 */
export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  { value, onChange, streaming, onSend, onStop, placeholder = '描述你的想法，或把剧本贴给我…' },
  ref,
) {
  const composing = useRef(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const autoGrow = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
  }

  useImperativeHandle(ref, () => ({
    fill: (text: string) => {
      onChange(text)
      requestAnimationFrame(() => {
        taRef.current?.focus()
        autoGrow()
      })
    },
    focus: () => taRef.current?.focus(),
  }))

  const submit = () => {
    const t = value.trim()
    if (!t || streaming) return
    onSend(t)
    onChange('')
    const ta = taRef.current
    if (ta) ta.style.height = 'auto'
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !composing.current) {
      e.preventDefault()
      submit()
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }

  return (
    <div className="composer-area">
      <div className="quick-chips">
        {['分镜建议', '剧本检查', '找灵感', 'Rundown'].map((c) => (
          <button key={c} className="quick-chip" onClick={() => onChange(`${c}：`)}>
            {c}
          </button>
        ))}
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <MicButton />
        <textarea
          ref={taRef}
          value={value}
          rows={1}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value)
            autoGrow()
          }}
          onKeyDown={onKeyDown}
          onCompositionStart={() => (composing.current = true)}
          onCompositionEnd={() => (composing.current = false)}
          aria-label="消息输入框"
        />
        {streaming ? (
          <button type="button" className={cn('send-btn', 'stop')} onClick={onStop} title="停止生成">
            <Square size={15} fill="currentColor" />
          </button>
        ) : (
          <button
            type="submit"
            className={cn('send-btn', !value.trim() && 'disabled')}
            title="发送（Enter）"
            disabled={!value.trim()}
          >
            <ArrowUp size={17} />
          </button>
        )}
      </form>
      <div className="composer-hint">Enter 发送 · Shift+Enter 换行 · 语音输入 Phase 2 接入 whisper-1</div>
    </div>
  )
})
