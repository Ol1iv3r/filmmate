import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent, type FormEvent } from 'react'
import { ArrowUp, Loader2, Paperclip, Square } from 'lucide-react'
import { cn } from '../lib/utils'
import { API_BASE } from '../lib/transport'
import { useI18n } from '../lib/i18n'
import { mergeTranscript } from '../lib/voiceInputMerge'
import { useVoiceInput } from '../hooks/useVoiceInput'
import { MicButton } from './MicButton'

export interface ComposerHandle {
  fill: (text: string) => void
  focus: () => void
  selectTool: (tool: string) => void
  openRefs: () => void
}

export interface SendMeta {
  tool?: string | null
  kind?: string | null
  themeIndex?: number | null
  storyboard?: Record<string, unknown>
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
  { labelZh: '找灵感', labelEn: 'Inspiration', tool: 'inspiration', hintZh: '选个题材吧～', hintEn: 'Pick a genre~' },
  { labelZh: '剧本检查/生成', labelEn: 'Script', tool: 'review', hintZh: '想写还是想查？', hintEn: 'Write or check?' },
  { labelZh: '分镜建议/生成', labelEn: 'Storyboard', tool: 'storyboard', hintZh: '先给我剧本～', hintEn: 'Script first~' },
  { labelZh: '拍摄计划', labelEn: 'Shooting plan', tool: 'schedule', hintZh: '说说你的档期～', hintEn: 'Your dates?' },
] as const

const INSPIRATION_KINDS = [
  { value: '电影', zh: '电影', en: 'Film' },
  { value: '电视剧', zh: '电视剧', en: 'TV series' },
  { value: '长片', zh: '长片', en: 'Feature' },
  { value: '短片', zh: '短片', en: 'Short' },
  { value: '竖屏短剧', zh: '竖屏短剧', en: 'Vertical drama' },
  { value: '广告/TVC', zh: '广告/TVC', en: 'Ad / TVC' },
  { value: '教程/产品演示', zh: '教程/产品演示', en: 'Tutorial' },
  { value: 'Vlog/美食', zh: 'Vlog/美食', en: 'Vlog / Food' },
  { value: '动画', zh: '动画', en: 'Animation' },
]

const KIND_HINTS: Record<string, { zh: string; en: string }> = {
  电影: { zh: '地点 / 人物 / 情绪，例：香港 雨夜 出租车司机 孤独', en: 'Place / character / mood, e.g. Hong Kong, rainy night, taxi driver' },
  电视剧: { zh: '人物关系 / 时代 / 集数感，例：九十年代东北 工厂家庭 三代人', en: 'Relationships / era, e.g. 90s factory family across three generations' },
  长片: { zh: '真实题材 / 观察对象，例：一座即将拆迁的县城电影院', en: 'Real subject, e.g. a county cinema about to be demolished' },
  短片: { zh: '一个概念 / 一个反转 / 一个瞬间，例：便利店最后一瓶牛奶', en: 'One idea / one twist, e.g. the last bottle of milk in a store' },
  竖屏短剧: { zh: '强钩子 / 爽点 / 身份反转，例：一睁眼回到 1998 年成了后妈', en: 'Strong hook / twist, e.g. waking up in 1998 as a stepmother' },
  '广告/TVC': { zh: '产品 / 卖点 / 目标人群 / 想给的感受，例：一款气泡水，想拍出夏天第一口的爽', en: 'Product / selling point / audience, e.g. sparkling water, the first sip of summer' },
  '教程/产品演示': { zh: '要演示的产品与功能，例：新手机的眼球追踪手势操作', en: 'Product & feature to demo, e.g. eye-tracking gestures on a new phone' },
  'Vlog/美食': { zh: '要拍的生活切片或美食，例：深夜街边一碗热汤面', en: 'A slice of life or food, e.g. a hot noodle bowl on a late-night street' },
  动画: { zh: '画风 / 世界观 / 一句话故事，例：水彩风的城市流浪猫', en: 'Art style / world / one-line story, e.g. watercolor city stray cat' },
}

/**
 * 输入区：多行、Enter 发送 / Shift+Enter 换行、中文输入法保护、
 * 流式中自动变停止按钮、自动增高。受控组件（空态示例卡一键填入）。
 *
 * 板块模式：点「找灵感 / 剧本检查·生成 / 分镜建议·生成 / 拍摄计划」后，
 * 之后输入的内容默认归该功能（不再往输入框里写「找灵感：」字样）。
 */
export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  { value, onChange, streaming, onSend, onStop, placeholder },
  ref,
) {
  const { lang } = useI18n()
  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en)
  const composing = useRef(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [inspOpen, setInspOpen] = useState(false)
  const [inspKind, setInspKind] = useState<string | null>(null)
  const [inspTheme, setInspTheme] = useState<number | null>(null)
  const [scriptFile, setScriptFile] = useState<{ name: string; chars: number; text: string } | null>(null)
  const [storyboardFile, setStoryboardFile] = useState<{
    name: string
    shots: unknown[]
    scene_count: number
    payload: Record<string, unknown>
  } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [refOpen, setRefOpen] = useState(false)
  const [refUrl, setRefUrl] = useState('')
  const [refTitle, setRefTitle] = useState('')
  const [refMoods, setRefMoods] = useState('')
  const [refMsg, setRefMsg] = useState('')
  const [refBusy, setRefBusy] = useState(false)

  const say = (zh: string, en: string) => {
    window.dispatchEvent(new CustomEvent('filmy:say', { detail: { zh, en } }))
  }

  useEffect(() => {
    const handler = (raw: Event) => {
      const detail = (raw as CustomEvent<{ index?: number; styleName?: string }>).detail
      const index = Number(detail?.index)
      if (!Number.isFinite(index)) return
      setInspTheme(index)
      setActiveTool('review')
      setInspOpen(false)
      onChange(t(`根据 Theme ${index + 1} 写一版剧本`, `Write a script for Theme ${index + 1}`))
      say(`已选 Theme ${index + 1}，接下来写这一套的剧本`, `Theme ${index + 1} selected — write the script next`)
      requestAnimationFrame(() => taRef.current?.focus())
    }
    window.addEventListener('filmmate:select-theme', handler)
    return () => window.removeEventListener('filmmate:select-theme', handler)
  }, [onChange, t])

  useImperativeHandle(ref, () => ({
    fill: (text: string) => {
      onChange(text)
      requestAnimationFrame(() => taRef.current?.focus())
    },
    focus: () => taRef.current?.focus(),
    selectTool: (tool: string) => {
      if (tool === 'inspiration') {
        setActiveTool('inspiration')
        setInspOpen(true)
      } else {
        setActiveTool(tool)
      }
      requestAnimationFrame(() => taRef.current?.focus())
    },
    openRefs: () => {
      setRefOpen(true)
      requestAnimationFrame(() => taRef.current?.focus())
    },
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
    const text = (value || '').trim()
    if (streaming || voiceInput.status === 'recording') return
    if (!text && !scriptFile && activeTool !== 'schedule') return
    if (storyboardFile && activeTool === 'storyboard') {
      const outgoing = text || t('分析这份分镜表，指出覆盖和节奏问题', 'Analyze this storyboard for coverage and pacing')
      onSend(outgoing, {
        tool: 'storyboard',
        kind: inspKind,
        themeIndex: inspTheme,
        storyboard: storyboardFile.payload,
      })
      return
    }
    let outgoing = text || (activeTool === 'storyboard'
      ? t('根据这份剧本出分镜', 'Generate a storyboard from this script')
      : activeTool === 'schedule'
        ? t('根据最近的分镜生成拍摄方案', 'Generate a shooting plan from the latest storyboard')
        : t('检查这份剧本，并告诉我冲突和修改建议', 'Check this script and tell me the conflicts'))
    if (activeTool !== 'inspiration' && scriptFile) outgoing += '\n\n【上传剧本】\n' + scriptFile.text
    onSend(outgoing, { tool: activeTool, kind: inspKind, themeIndex: inspTheme })
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
      if (file.name.toLowerCase().endsWith('.csv')) {
        const form = new FormData()
        form.append('file', file)
        const csvRes = await fetch((API_BASE ?? '') + '/api/storyboard/parse', { method: 'POST', body: form })
        const csvData = await csvRes.json().catch(() => ({}))
        if (!csvRes.ok) throw new Error(csvData.detail || t('分镜 CSV 解析失败', 'Storyboard CSV parse failed'))
        const payload = {
          kind: 'storyboard',
          shots: csvData.shots ?? [],
          scene_count: csvData.scene_count ?? 0,
          logline: null,
        }
        setStoryboardFile({
          name: csvData.filename ?? file.name,
          shots: payload.shots,
          scene_count: payload.scene_count,
          payload,
        })
        setScriptFile(null)
        setActiveTool('storyboard')
        setInspOpen(false)
        return
      }
      const form = new FormData()
      form.append('file', file)
      const res = await fetch((API_BASE ?? '') + '/api/script/parse', { method: 'POST', body: form })
      if (!res.ok) {
        const detail = await res.text()
        throw new Error(t('解析失败：', 'Parse failed: ') + detail.slice(0, 140))
      }
      const data = await res.json()
      setStoryboardFile(null)
      setScriptFile({
        name: data.filename ?? file.name,
        chars: Number(data.chars ?? (data.text ?? '').length),
        text: String(data.text ?? ''),
      })
      // Uploading a script promises "Enter to analyze"; make that true even
      // if the user was still on the Inspiration tab.
      if (activeTool === null || activeTool === 'inspiration') {
        setActiveTool('review')
        setInspOpen(false)
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : t('剧本上传失败', 'Upload failed'))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const addReferenceFilm = async () => {
    const urls = refUrl
      .split(/[\s,，、;；]+/)
      .map((x) => x.trim())
      .filter(Boolean)
    if (!urls.length) {
      setRefMsg(t('至少贴一个 Bilibili / YouTube 链接', 'Paste at least one Bilibili / YouTube link'))
      return
    }
    setRefBusy(true)
    setRefMsg('')
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 120_000)
    try {
      const res = await fetch((API_BASE ?? '') + '/api/library/personal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          urls,
          title: urls.length === 1 ? refTitle.trim() : '',
          moods: refMoods.split(/[,，、]/).map((x) => x.trim()).filter(Boolean),
          lang,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || t('加入失败', 'Failed'))
      const films: Array<{ title?: string; style_summary?: string }> = data.films || (data.film ? [data.film] : [])
      const errors: Array<{ url?: string; error?: string }> = data.errors || []
      if (!films.length) throw new Error(errors[0]?.error || t('加入失败', 'Failed'))
      const first = films[0]
      let message = t(
        `已加入 ${films.length} 部参考片，并完成风格分析`,
        `Added ${films.length} reference film${films.length === 1 ? '' : 's'} and analysed the style`,
      )
      if (first?.style_summary) message += ` · ${first.style_summary}`
      if (errors.length) {
        message += t(
          `；${errors.length} 条失败：${errors[0]?.error ?? ''}`,
          `; ${errors.length} failed: ${errors[0]?.error ?? ''}`,
        )
      }
      setRefMsg(message)
      setRefUrl('')
      setRefTitle('')
      setRefMoods('')
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setRefMsg(t('加入超时，请稍后重试', 'Adding timed out; please retry'))
      } else {
        setRefMsg(err instanceof Error ? err.message : t('加入失败', 'Failed'))
      }
    } finally {
      window.clearTimeout(timer)
      setRefBusy(false)
    }
  }

  const handleChip = (tool: string, hintZh: string, hintEn: string) => {
    say(hintZh, hintEn)
    if (tool === 'inspiration') {
      setActiveTool('inspiration')
      setInspOpen(true)
      taRef.current?.focus()
      return
    }
    if (tool === 'schedule') {
      setActiveTool('schedule')
      taRef.current?.focus()
      return
    }
    if (tool === 'storyboard' && !scriptFile && !storyboardFile) {
      setUploadError(t('分镜需要先上传剧本：点左侧回形针上传 PDF/DOCX/TXT；或用「剧本检查/生成」先写一版。',
        'Storyboard needs a script: upload PDF/DOCX/TXT with the paperclip, or write one first.'))
    }
    setActiveTool(tool)
    taRef.current?.focus()
  }

  const kindLabel = (value: string) => {
    const item = INSPIRATION_KINDS.find((k) => k.value === value)
    return item ? (lang === 'zh' ? item.zh : item.en) : value
  }

  const kindHint = inspKind ? (KIND_HINTS[inspKind] ?? { zh: t('用一句话描述你想要的感觉', 'Describe the feeling in one line'), en: 'Describe the feeling in one line' }) : null

  const modeHint = activeTool === 'inspiration'
    ? inspKind
      ? t('正在找「' + kindLabel(inspKind) + '」的灵感 · ', 'Finding inspiration for ' + kindLabel(inspKind) + ' · ') + (lang === 'zh' ? kindHint?.zh : kindHint?.en)
      : t('找灵感：先选题材，再用一句话描述你想要的感觉', 'Inspiration: pick a genre, then describe the feeling')
    : activeTool === 'schedule'
      ? t('拍摄计划：可先说偏好（避开哪些日期 / 几天拍完 / 每天工时 / 地点限制），回车生成；直接回车 = 按默认排期',
        'Shooting plan: state preferences (dates to avoid / days / hours / locations), then Enter; empty Enter = default plan')
      : activeTool === 'review' && inspTheme !== null
        ? t(`已选 Theme ${inspTheme + 1}，回车生成这一套的剧本`, `Theme ${inspTheme + 1} selected — press Enter to write that script`)
        : activeTool
        ? t('当前功能：', 'Active tool: ') + (TOOL_CHIPS.find((c) => c.tool === activeTool)?.labelZh ?? '') + t('（可先上传剧本）', ' (upload a script first)')
        : ''

  return (
    <div className="composer-area">
      <div className="quick-chips">
        {TOOL_CHIPS.map((c) => (
          <button
            key={c.tool}
            className={cn('quick-chip', activeTool === c.tool && 'active')}
            onClick={() => handleChip(c.tool, c.hintZh, c.hintEn)}
          >
            {lang === 'zh' ? c.labelZh : c.labelEn}
          </button>
        ))}
        <button className="quick-chip" onClick={() => setRefOpen((v) => !v)}>
          {t('＋参考片', '+ Reference film')}
        </button>
      </div>

      {inspOpen && (
        <div className="quick-chips kind-chips">
          <span className="kind-label">{t('先选题材：', 'Pick a genre: ')}</span>
          {INSPIRATION_KINDS.map((k) => (
            <button
              key={k.value}
              className={cn('quick-chip', inspKind === k.value && 'active')}
              onClick={() => {
                setInspKind(k.value)
                setInspTheme(null)
                setInspOpen(false)
                taRef.current?.focus()
              }}
            >
              {lang === 'zh' ? k.zh : k.en}
            </button>
          ))}
        </div>
      )}

      {activeTool === 'schedule' && (
        <div className="quick-chips">
          <span className="kind-label">{t('快捷偏好：', 'Quick prefs: ')}</span>
          {[
            { zh: '3天内拍完', en: 'Within 3 days' },
            { zh: '避开周末', en: 'Avoid weekends' },
            { zh: '每天10小时', en: '10 hours/day' },
            { zh: '夜戏集中', en: 'Night scenes' },
            { zh: '日戏为主', en: 'Day scenes' },
            { zh: '场地固定在一个地方', en: 'One location' },
          ].map((pref) => (
            <button
              key={pref.zh}
              className="quick-chip"
              onClick={() => {
                const text = lang === 'zh' ? pref.zh : pref.en
                onChange(value.trim() ? value.replace(/[，,\s]+$/, '') + '，' + text : text)
                taRef.current?.focus()
              }}
            >
              {lang === 'zh' ? pref.zh : pref.en}
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
              setInspTheme(null)
              setInspOpen(false)
            }}
          >
            {t('退出该功能', 'Exit')}
          </button>
        </div>
      )}

      {scriptFile && (
        <div className="composer-mode">
          {t('已上传剧本：', 'Script: ')}{scriptFile.name}（{scriptFile.chars} {t('字', 'chars')}）· {t('可直接回车开始分析', 'Enter to analyze')}
          <button className="link-btn" onClick={() => setScriptFile(null)}>{t('移除', 'Remove')}</button>
        </div>
      )}
      {storyboardFile && (
        <div className="composer-mode">
          {t('已上传分镜 CSV：', 'Storyboard CSV: ')}{storyboardFile.name}（{storyboardFile.shots.length} {t('个镜头', 'shots')}）· {t('回车分析分镜', 'Enter to analyze')}
          <button className="link-btn" onClick={() => setStoryboardFile(null)}>{t('移除', 'Remove')}</button>
        </div>
      )}

      {refOpen && (
        <div className="ref-form">
          <div className="ref-form-title">
            {t('加入你想参考的电影（AI 会分析风格，并在后续推荐里贴近你的品味）',
              'Add reference films (AI learns the style and tailors recommendations)')}
          </div>
          <textarea
            className="ref-input ref-urls"
            rows={3}
            placeholder={t('链接（Bilibili / YouTube），一行一个，可批量粘贴', 'Links (Bilibili / YouTube), one per line — batch paste supported')}
            value={refUrl}
            onChange={(e) => setRefUrl(e.target.value)}
          />
          <input className="ref-input" placeholder={t('片名（单条链接时可选，会自动抓取）', 'Title (optional for a single link, auto-fetched)')} value={refTitle} onChange={(e) => setRefTitle(e.target.value)} />
          <input className="ref-input" placeholder={t('情绪/标签（逗号分隔，可选）：压抑、长镜头、北欧', 'Moods/tags (optional): bleak, long take, Nordic')} value={refMoods} onChange={(e) => setRefMoods(e.target.value)} />
          <div className="ref-form-actions">
            <button className="panel-btn" onClick={() => void addReferenceFilm()} disabled={refBusy}>
              {refBusy ? t('加入并分析中…', 'Adding & analyzing…') : t('加入参考片', 'Add reference film(s)')}
            </button>
            <button className="link-btn" onClick={() => setRefOpen(false)}>{t('收起', 'Close')}</button>
          </div>
          {refMsg && <div className="ref-msg">{refMsg}</div>}
        </div>
      )}

      {uploadError && <div className="composer-error" role="alert">{uploadError}</div>}

      <form className="composer" onSubmit={onSubmit}>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.markdown,.fountain,.csv"
          style={{ display: 'none' }}
          onChange={(e) => void onPickFile(e.target.files?.[0])}
        />
        <button
          type="button"
          className="attach-btn"
          title={t('上传剧本（PDF / DOCX / TXT）', 'Upload script (PDF / DOCX / TXT)')}
          disabled={streaming || uploading}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? <Loader2 size={15} className="spin" /> : <Paperclip size={15} />}
        </button>
        <MicButton
          status={voiceInput.status}
          elapsedMs={voiceInput.elapsedMs}
          supported={voiceInput.supported}
          engine={voiceInput.engine}
          disabled={streaming}
          onStart={() => void voiceInput.start()}
          onStop={() => void voiceInput.stop()}
        />
        <textarea
          ref={taRef}
          value={value}
          rows={1}
          placeholder={inspKind
            ? t('找「' + kindLabel(inspKind) + '」的灵感：', 'Inspiration for ' + kindLabel(inspKind) + ': ') + (lang === 'zh' ? kindHint?.zh : kindHint?.en)
            : (placeholder ?? t('描述你的想法，或把剧本贴给我…', 'Describe your idea, or paste a script…'))}
          onChange={(e) => {
            onChange(e.target.value)
            autoGrow()
          }}
          onKeyDown={onKeyDown}
          onCompositionStart={() => (composing.current = true)}
          onCompositionEnd={() => (composing.current = false)}
          aria-label={t('消息输入框', 'Message input')}
        />
        {streaming ? (
          <button type="button" className={cn('send-btn', 'stop')} onClick={onStop} title={t('停止生成', 'Stop')}>
            <Square size={15} fill="currentColor" />
          </button>
        ) : (
          <button
            type="submit"
            className={cn('send-btn', !value.trim() && !scriptFile && activeTool !== 'schedule' && 'disabled')}
            title={scriptFile && !value.trim() ? t('直接开始分析已上传剧本（Enter）', 'Analyze uploaded script (Enter)') : t('发送（Enter）', 'Send (Enter)')}
            disabled={!value.trim() && !scriptFile && activeTool !== 'schedule'}
          >
            <ArrowUp size={17} />
          </button>
        )}
      </form>
      {voiceInput.error && <div className="composer-error" role="alert">{voiceInput.error}</div>}
      <div className="composer-hint">
        {t('Enter 发送 · Shift+Enter 换行 · 点上方板块后输入内容默认归该功能 · 上传剧本后可直接回车开始分析',
          'Enter to send · Shift+Enter for newline · chips set the active tool · Enter analyzes an uploaded script')}
      </div>
    </div>
  )
})
