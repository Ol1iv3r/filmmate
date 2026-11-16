import { forwardRef, useImperativeHandle, useRef, useState, type KeyboardEvent, type FormEvent } from 'react'
import { ArrowUp, Loader2, Paperclip, Square } from 'lucide-react'
import { cn } from '../lib/utils'
import { API_BASE } from '../lib/transport'
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
  const fileRef = useRef<HTMLInputElement>(null)
  const [inspOpen, setInspOpen] = useState(false)
  const [inspKind, setInspKind] = useState<string | null>(null)
  const [scriptFile, setScriptFile] = useState<{ name: string; chars: number; text: string } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')

  const onPickFile = async (file: File | undefined) => {
    if (!file) return
    setUploadError('')
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch((API_BASE ?? '') + '/api/script/parse', { method: 'POST', body: form })
      if (!res.ok) {
        const detail = await res.text()
        throw new Error('解析失败：' + detail.slice(0, 140))
      }
      const data = await res.json()
      setScriptFile({
        name: data.filename ?? file.name,
        chars: Number(data.chars ?? (data.text ?? '').length),
        text: String(data.text ?? ''),
      })
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : '剧本上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

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
    let outgoing = inspKind ? `【题材：${inspKind}】\n${t}` : t
    // 上传过剧本时，把原文附在消息末尾（后端识别后再做检查/改格式/分镜）
    if (!inspKind && scriptFile) outgoing += '\n\n【上传剧本】\n' + scriptFile.text
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
        {['找灵感', '剧本检查/生成', '分镜建议/生成', '拍摄计划'].map((c) => (
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
              if (c === '分镜建议/生成' && !scriptFile) {
                setUploadError('分镜需要先上传剧本：点左侧回形针上传 PDF/DOCX/TXT')
              }
              if (c === '剧本检查/生成' && !scriptFile) {
                onChange('写剧本：')
              } else {
                onChange(`${c}：`)
              }
              taRef.current?.focus()
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
      {scriptFile && (
        <div className="composer-mode">
          已上传剧本：{scriptFile.name}（{scriptFile.chars} 字）
          <button className="link-btn" onClick={() => setScriptFile(null)}>移除</button>
        </div>
      )}
      {uploadError && <div className="composer-error" role="alert">{uploadError}</div>}
      <form className="composer" onSubmit={onSubmit}>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.markdown,.fountain"
          style={{ display: 'none' }}
          onChange={(e) => void onPickFile(e.target.files?.[0])}
        />
        <button
          type="button"
          className="attach-btn"
          title="上传剧本（PDF / DOCX / TXT）"
          disabled={streaming || uploading}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? <Loader2 size={15} className="spin" /> : <Paperclip size={15} />}
        </button>
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
