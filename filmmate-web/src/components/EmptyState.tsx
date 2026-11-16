import { useState } from 'react'
import { CalendarClock, Clapperboard, Lightbulb, Plus, ScrollText, Sparkles } from 'lucide-react'
import { isMockMode } from '../lib/transport'
import { useI18n } from '../lib/i18n'
import { FilmyMark } from './FilmyMark'
import { cn } from '../lib/utils'

export type HomeTool = 'inspiration' | 'review' | 'storyboard' | 'schedule' | 'refs'

interface ToolBrief {
  key: HomeTool
  icon: React.ReactNode
  zh: { name: string; desc: string; how: string; hint: string }
  en: { name: string; desc: string; how: string; hint: string }
}

const TOOL_BRIEFS: ToolBrief[] = [
  {
    key: 'inspiration',
    icon: <Lightbulb size={15} />,
    zh: { name: '找灵感', desc: '按题材找真实影片参考', how: '选题材 → 一句话描述感觉', hint: '选个题材吧～' },
    en: { name: 'Find inspiration', desc: 'Real film references by genre', how: 'Pick a genre → describe a feeling', hint: 'Pick a genre~' },
  },
  {
    key: 'review',
    icon: <ScrollText size={15} />,
    zh: { name: '剧本检查/生成', desc: '查冲突，或按主题写剧本', how: '上传剧本回车，或直接说主题', hint: '想写还是想查？' },
    en: { name: 'Script check / write', desc: 'Check conflicts or write by theme', how: 'Upload + Enter, or say a theme', hint: 'Write or check?' },
  },
  {
    key: 'storyboard',
    icon: <Clapperboard size={15} />,
    zh: { name: '分镜建议/生成', desc: '按剧本逐场出镜头表', how: '先上传剧本 → 点生成', hint: '先给我剧本～' },
    en: { name: 'Storyboard', desc: 'Scene-by-scene shot list', how: 'Upload script → generate', hint: 'Script first~' },
  },
  {
    key: 'schedule',
    icon: <CalendarClock size={15} />,
    zh: { name: '拍摄计划', desc: '按最近分镜排拍摄日', how: '说偏好，如 3 天、避开周末', hint: '说说你的档期～' },
    en: { name: 'Shooting plan', desc: 'Shoot days from last storyboard', how: 'Say prefs: 3 days, avoid weekends', hint: 'Your dates?' },
  },
  {
    key: 'refs',
    icon: <Plus size={15} />,
    zh: { name: '+参考片', desc: '收藏喜欢的片，AI 学你的口味', how: '贴 B站/YouTube 链接即可', hint: '加部心头好～' },
    en: { name: '+ Reference film', desc: 'Save films you love, AI learns taste', how: 'Paste a Bilibili/YouTube link', hint: 'Add a favorite~' },
  },
]

/** 首页：品牌 + 五个板块；点板块展示极短介绍与操作说明，不再堆示例卡。 */
export function EmptyState({
  onStartTool,
  onOpenRefs,
}: {
  onStartTool: (tool: HomeTool) => void
  onOpenRefs: () => void
}) {
  const { lang } = useI18n()
  const [active, setActive] = useState<HomeTool | null>(null)

  const pick = (tool: ToolBrief) => {
    setActive(tool.key)
    const detail = lang === 'zh' ? tool.zh : tool.en
    window.dispatchEvent(new CustomEvent('filmy:say', { detail: { zh: tool.zh.hint, en: tool.en.hint } }))
    void detail
  }

  const activeBrief = TOOL_BRIEFS.find((t) => t.key === active) ?? null
  const text = (brief: ToolBrief) => (lang === 'zh' ? brief.zh : brief.en)

  return (
    <div className="empty-state">
      <div className="hero hero-home">
        <div className="hero-logo">
          <FilmyMark size={46} />
        </div>
        <h2 className="hero-title">
          {lang === 'zh' ? '你的 AI 创作顾问' : 'Your AI film consultant'}
          <span className="hero-dot">.</span>
        </h2>
        <p className="hero-sub">
          {lang === 'zh'
            ? '找灵感 → 剧本 → 分镜 → 拍摄计划，每个回答都有真实影片样本做依据。'
            : 'Inspiration → Script → Storyboard → Shooting plan, grounded in real film references.'}
        </p>
      </div>

      <div className="home-chips">
        {TOOL_BRIEFS.map((brief) => (
          <button
            key={brief.key}
            className={cn('home-chip', active === brief.key && 'active')}
            onClick={() => pick(brief)}
          >
            {brief.icon}
            <span>{text(brief).name}</span>
          </button>
        ))}
      </div>

      {activeBrief ? (
        <div className="tool-brief">
          <div className="tool-brief-head">
            <span className="tool-brief-icon">{activeBrief.icon}</span>
            <span className="tool-brief-name">{text(activeBrief).name}</span>
          </div>
          <p className="tool-brief-desc">{text(activeBrief).desc}</p>
          <p className="tool-brief-how">
            {lang === 'zh' ? '怎么用：' : 'How: '}
            {text(activeBrief).how}
          </p>
          <button
            className="panel-btn"
            onClick={() => {
              if (activeBrief.key === 'refs') onOpenRefs()
              else onStartTool(activeBrief.key)
            }}
          >
            {lang === 'zh' ? '开始' : 'Start'}
          </button>
        </div>
      ) : null}

      {isMockMode && (
        <div className="mock-note">
          {lang === 'zh' ? (
            <>当前为<strong>本地演示模式</strong>（无后端，流式与工具调用由 mock 引擎模拟）。</>
          ) : (
            <>Currently in <strong>local demo mode</strong> (no backend; streaming and tools are simulated).</>
          )}
        </div>
      )}
    </div>
  )
}
