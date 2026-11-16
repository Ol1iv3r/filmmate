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

export interface SendMeta {
  tool?: string | null
  kind?: string | null
}

interface ComposerProps {
  value: string
  onChange: (text: string) => void
  streaming: boolean
  onSend: (text: string, meta?: SendMeta) => void
  onStop: () => void
  placeholder?: string
}

const TOOL_CHIPS = [
  { label: '找灵感', tool: 'inspiration' },
  { label: '剧本检查/生成', tool: 'review' },
  { label: '分镜建议/生成', tool: 'storyboard' },
  { label: '拍摄计划', tool: 'schedule' },
] as const

const INSPIRATION_KINDS = ['电影', '电视剧', '长片', '短片', '竖屏短剧', '广告/TVC', '教程/产品演示', 'Vlog/美食', '动画']

const KIND_HINTS: Record<string, string> = {
  电影: '地点 / 人物 / 情绪，例：香港 雨夜 出租车司机 孤独',
  电视剧: '人物关系 / 时代 / 集数感，例：九十年代东北 工厂家庭 三代人',
  长片: '真实题材 / 观察对象，例：一座即将拆迁的县城电影院',
  短片: '一个概念 / 一个反转 / 一个瞬间，例：便利店最后一瓶牛奶',
  竖屏短剧: '强钩子 / 爽点 / 身份反转，例：一睁眼回到 1998 年成了后妈',
  '广告/TVC': '产品 / 卖点 / 目标人群 / 想给的感受，例：一款气泡水，想拍出夏天第一口的爽',
  '教程/产品演示': '要演示的产品与功能，例：新手机的眼球追踪手势操作',
  'Vlog/美食': '要拍的生活切片或美食，例：深夜街边一碗热汤面',
  动画: '画风 / 世界观 / 一句话故事，例：水彩风的城市流浪猫',
}

const TOOL_LABELS: Record<string, string> = {
  inspiration: '找灵感',
  review: '剧本检查/生成',
  storyboard: '分镜建议/生成',
  schedule: '拍摄计划',
}

/**
 * 输入区：多行、Enter 发送 / Shift+Enter 换行、中文输入法保护、
 * 流式中自动变停止按钮、自动增高。受控组件（空态示例卡一键填入）。
 *
 * 板块模式：点「找灵感 / 剧本检查·生成 / 分镜建议·生成 / 拍摄计划」后，
 * 之后输入的内容默认归该功能（不再往输入框里写「找灵感：」字样）。
 */
export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  { value, onChange, streaming, onSend, onStop, placeholder = '描述你的想法，或把剧本贴给我…' },
  ref,
) {
  const composing = useRef(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [inspOpen, setInspOpen] = useState(false)
  const [inspKind, setInspKind] = useState<string | null>(null)
  const [scriptFile, setScriptFile] = useState<{ name: string; chars: number; text: string } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [refOpen, setRefOpen] = useState(false)
  const [refUrl, setRefUrl] = useState('')
  const [refTitle, setRefTitle] = useState('')
  const [refMoods, setRefMoods] = useState('')
  const [refMsg, setRefMsg] = useState('')
  const [refBusy, setRefBusy] = useState(false)

  useImperativeHandle(ref, () => ({
    fill: (text: string) => {
      onChange(text)
      requestAnimationFrame(() => taRef.current?.focus())
    },
    focus: () => taRef.current?.focus(),
  }))

  const voiceInput = useVoiceInput({
    onTranscript: (text) => onChange(mergeTranscript(value, text)),
  })

  const autoGrow = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'
  }

  const submit = () => {
    const t = (value || '').trim()
    if (streaming || voiceInput.status === 'recording') return
    if (!t && !scriptFile) return
    // 上传了剧本但没打字：直接回车按当前板块的默认动作执行
    let outgoing = t || (activeTool === 'storyboard'
      ? '根据这份剧本出分镜'
      : activeTool === 'schedule'
        ? '根据最近的分镜生成拍摄方案'
        : '检查这份剧本，并告诉我冲突和修改建议')
    // 上传过剧本时，把原文附在消息末尾（后端识别；输入框里不显示）
    if (activeTool !== 'inspiration' && scriptFile) outgoing += '\n\n【上传剧本】\n' + scriptFile.text
    onSend(outgoing, { tool: activeTool, kind: inspKind })
    onChange('')
    const ta = taRef.current
    if (ta) ta.style.height = 'auto'
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !composing.current) {
      e.preventDefault()
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

  const addReferenceFilm = async () => {
    if (!refUrl.trim() && !refTitle.trim()) {
      setRefMsg('至少填链接或片名')
      return
    }
    setRefBusy(true)
    setRefMsg('')
    try {
      const res = await fetch((API_BASE ?? '') + '/api/library/personal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: refUrl.trim(), title: refTitle.trim(),
          moods: refMoods.split(/[,，、]/).map((x) => x.trim()).filter(Boolean),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || '加入失败')
      setRefMsg('已加入参考片：' + (data.film?.title ?? refTitle ?? refUrl) + (data.film?.style_summary ? ' · ' + data.film.style_summary : ''))
      setRefUrl('')
      setRefTitle('')
      setRefMoods('')
    } catch (err) {
      setRefMsg(err instanceof Error ? err.message : '加入失败')
    } finally {
      setRefBusy(false)
    }
  }

  const handleChip = (tool: string) => {
    if (tool === 'inspiration') {
      setActiveTool('inspiration')
      setInspOpen(true)
      taRef.current?.focus()
      return
    }
    if (tool === 'schedule') {
      setActiveTool('schedule')
      // 拍摄计划：直接用「最近一版分镜」生成详细方案（由 ChatPanel 补 storyboard 数据）
      onSend('根据最近的分镜，生成详细的拍摄方案', { tool: 'schedule' })
      return
    }
    if (tool === 'storyboard' && !scriptFile) {
      setUploadError('分镜需要先上传剧本：点左侧回形针上传 PDF/DOCX/TXT；或用「剧本检查/生成」先写一版。')
    }
    setActiveTool(tool)
    taRef.current?.focus()
  }

  const modeHint = activeTool === 'inspiration'
    ? inspKind
      ? '正在找「' + inspKind + '」的灵感 · ' + (KIND_HINTS[inspKind] ?? '用一句话描述你想要的感觉')
      : '找灵感：先选题材，再用一句话描述你想要的感觉'
    : activeTool
      ? '当前功能：' + (TOOL_LABELS[activeTool] ?? activeTool) + (activeTool === 'review' || activeTool === 'storyboard' ? '（可先上传剧本）' : '')
      : ''

  return (
    <div className="composer-area">
      <div className="quick-chips">
        {TOOL_CHIPS.map((c) => (
          <button
            key={c.tool}
            className={cn('quick-chip', activeTool === c.tool && 'active')}
            onClick={() => handleChip(c.tool)}
          >
            {c.label}
          </button>
        ))}
        <button className="quick-chip" onClick={() => setRefOpen((v) => !v)}>＋参考片</button>
      </div>

      {inspOpen && (
        <div className="quick-chips kind-chips">
          <span className="kind-label">先选题材：</span>
          {INSPIRATION_KINDS.map((k) => (
            <button
              key={k}
              className={cn('quick-chip', inspKind === k && 'active')}
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

      {modeHint && (
        <div className="composer-mode">
          {modeHint}
          <button
            className="link-btn"
            onClick={() => {
              setActiveTool(null)
              setInspKind(null)
              setInspOpen(false)
            }}
          >
            退出该功能
          </button>
        </div>
      )}

      {scriptFile && (
        <div className="composer-mode">
          已上传剧本：{scriptFile.name}（{scriptFile.chars} 字）· 可直接回车开始分析
          <button className="link-btn" onClick={() => setScriptFile(null)}>移除</button>
        </div>
      )}

      {refOpen && (
        <div className="ref-form">
          <div className="ref-form-title">加入你想参考的电影（AI 会分析风格，并在后续推荐里贴近你的品味）</div>
          <input className="ref-input" placeholder="链接（Bilibili / YouTube）" value={refUrl} onChange={(e) => setRefUrl(e.target.value)} />
          <input className="ref-input" placeholder="片名（可不填，会自动抓取）" value={refTitle} onChange={(e) => setRefTitle(e.target.value)} />
          <input className="ref-input" placeholder="情绪/标签（逗号分隔，可选）：压抑、长镜头、北欧" value={refMoods} onChange={(e) => setRefMoods(e.target.value)} />
          <div className="ref-form-actions">
            <button className="panel-btn" onClick={() => void addReferenceFilm()} disabled={refBusy}>
              {refBusy ? '分析中…' : '加入参考片'}
            </button>
            <button className="link-btn" onClick={() => setRefOpen(false)}>收起</button>
          </div>
          {refMsg && <div className="ref-msg">{refMsg}</div>}
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
          placeholder={inspKind ? '找「' + inspKind + '」的灵感：' + (KIND_HINTS[inspKind] ?? '描述你想要的感觉…') : placeholder}
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
            className={cn('send-btn', !value.trim() && !scriptFile && 'disabled')}
            title={scriptFile && !value.trim() ? '直接开始分析已上传剧本（Enter）' : '发送（Enter）'}
            disabled={!value.trim() && !scriptFile}
          >
            <ArrowUp size={17} />
          </button>
        )}
      </form>
      {voiceInput.error && <div className="composer-error" role="alert">{voiceInput.error}</div>}
      <div className="composer-hint">
        Enter 发送 · Shift+Enter 换行 · 点上方板块后输入内容默认归该功能 · 上传剧本后可直接回车开始分析
      </div>
    </div>
  )
})
