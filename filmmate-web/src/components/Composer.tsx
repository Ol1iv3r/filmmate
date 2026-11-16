import { forwardRef, useImperativeHandle, useRef, useState, type KeyboardEvent, type FormEvent } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import { cn } from '../lib/utils'
import { mergeTranscript } from '../lib/voiceInputMerge'
import { useVoiceInput } from '../hooks/useVoiceInput'
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
const INSPIRATION_KINDS = ['电影', '电视剧', '长片', '短片', '竖屏短剧', '广告/TVC', '教程/产品演示', 'Vlog/美食', '动画']

export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  { value, onChange, streaming, onSend, onStop, placeholder = '描述你的想法，或把剧本贴给我…' },
  ref,
) {
  const composing = useRef(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [inspOpen, setInspOpen] = useState(false)
  const [inspKind, setInspKind] = useState<string | null>(null)

  // Phase 2 语音输入（voice input）：录音状态机放在输入区本地，
  // 转写结果只并入草稿，永不自动发送。
  const voiceInput = useVoiceInput({
    onTranscript: (text) => onChange(mergeTranscript(value, text)),
  })

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
    if (!t || streaming || voiceInput.status === 'recording') return
    // 找灵感：把用户选的题材随消息一起发给后端（后端用它划分库）
    const outgoing = inspKind ? `【题材：${inspKind}】\n${t}` : t
    onSend(outgoing)
    onChange('')
    setInspKind(null)
    setInspOpen(false)
    const ta = taRef.current
    if (ta) ta.style.height = 'auto'
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !composing.current) {
      e.preventDefault()
      // 录音时 Enter = 停止并转写，避免把半句话发出去。
      if (voiceInput.status === 'recording') {
        void voiceInput.stop()
        return
      }
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
        {['找灵感', '出分镜', '分镜建议', '剧本检查', 'Rundown'].map((c) => (
          <button
            key={c}
            className="quick-chip"
            onClick={() => {
              if (c === '找灵感') {
                setInspOpen(true)
                if (!value.trim()) onChange('找灵感：')
                taRef.current?.focus()
                return
              }
              if (c === '出分镜') {
                onChange('出分镜：')
                taRef.current?.focus()
                return
              }
              onChange(`${c}：`)
            }}
          >
            {c}
          </button>
        ))}
      </div>
      {inspOpen && (
        <div className="quick-chips kind-chips">
          <span className="kind-label">先选题材：</span>
          {INSPIRATION_KINDS.map((k) => (
            <button
              key={k}
              className="quick-chip"
              onClick={() => {
                setInspKind(k)
                setInspOpen(false)
                taRef.current?.focus()
              }}
            >
              {k}
            </button>
          ))}
        </div>
      )}
      {inspKind && (
        <div className="composer-mode">
          正在找「{inspKind}」的灵感 · 用一句话描述感觉（地点 / 情绪 / 场景），例：香港 雨夜 旧楼 孤独
        </div>
      )}
      <form className="composer" onSubmit={onSubmit}>
        <MicButton
          status={voiceInput.status}
          elapsedMs={voiceInput.elapsedMs}
          supported={voiceInput.supported}
          disabled={streaming}
          onStart={() => void voiceInput.start()}
          onStop={() => void voiceInput.stop()}
        />
        <textarea
          ref={taRef}
          value={value}
          rows={1}
          placeholder={inspKind ? `找「${inspKind}」的灵感：描述你想要的感觉…` : placeholder}
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
      {voiceInput.error && (
        <div className="composer-error" role="alert">
          {voiceInput.error}
        </div>
      )}
      <div className="composer-hint">
        Enter 发送 · Shift+Enter 换行 · 麦克风：点一下开始，再点停止（Esc 取消），文字只进输入框
      </div>
    </div>
  )
})
