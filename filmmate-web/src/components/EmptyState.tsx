import { Clapperboard, Sparkles, ScrollText, ListTodo, Lightbulb, CalendarClock } from 'lucide-react'
import { isMockMode } from '../lib/transport'

export interface ExamplePrompt {
  icon: React.ReactNode
  label: string
  prompt: string
}

export const EXAMPLES: ExamplePrompt[] = [
  {
    icon: <Sparkles size={16} />,
    label: '出分镜（会先检索样本库）',
    prompt: '给一个 30 秒可爱宠物零食广告出分镜，参考样本库里类似风格的片子',
  },
  {
    icon: <ScrollText size={16} />,
    label: '检查剧本漏洞',
    prompt:
      '帮我检查这段剧本的漏洞：第1场 天台 夜 小明：今晚的月亮真圆。小红：嗯，和去年一样。第2场 天台 日 小明：你不是出国了吗？怎么还在香港？小红：我根本没走。',
  },
  {
    icon: <CalendarClock size={16} />,
    label: '排拍摄 Rundown',
    prompt: '帮我排一个校园短片 2 小时拍摄 rundown，6 人小团队单机',
  },
]

/** 空会话引导页：品牌 + 能力卡片 + 3 个示例 prompt 一键填入。 */
export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="empty-state">
      <div className="hero">
        <div className="hero-logo">
          <Clapperboard size={30} />
        </div>
        <h2 className="hero-title">
          你的 AI 创作顾问<span className="hero-dot">.</span>
        </h2>
        <p className="hero-sub">
          把想法或剧本交给我 —— 找灵感 → 查剧本漏洞 → 出分镜 → 排 Rundown → 规划日程，
          每个回答都有真实影片样本做依据。
        </p>
        <div className="hero-capabilities">
          <span><Lightbulb size={13} /> 找灵感</span>
          <span><ScrollText size={13} /> 查剧本漏洞</span>
          <span><Clapperboard size={13} /> 出分镜</span>
          <span><ListTodo size={13} /> 排 Rundown</span>
        </div>
      </div>

      <div className="example-cards">
        {EXAMPLES.map((ex) => (
          <button key={ex.label} className="example-card" onClick={() => onPick(ex.prompt)}>
            <span className="example-icon">{ex.icon}</span>
            <span className="example-label">{ex.label}</span>
            <span className="example-text">{ex.prompt.length > 60 ? ex.prompt.slice(0, 60) + '…' : ex.prompt}</span>
          </button>
        ))}
      </div>

      {isMockMode && (
        <div className="mock-note">
          当前为<strong>本地演示模式</strong>（无后端，流式与工具调用由 mock 引擎模拟）。
          接入 Jacky 的 AI SDK 后端后会自动切换：在 <code>.env</code> 里填 <code>VITE_API_BASE</code> 即可。
        </div>
      )}
    </div>
  )
}
