import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { cn } from '../lib/utils'

type Mood = 'idle' | 'wave' | 'think'

interface DownloadAnchor {
  left: number
  top: number
}

const GREETINGS: Array<{ zh: string; en: string }> = [
  { zh: '嗨～我是 Filmy', en: 'Hi, I am Filmy' },
  { zh: '今天拍点什么？', en: 'What are we shooting?' },
  { zh: '陪你一起想～', en: 'Thinking with you~' },
  { zh: '累了就歇会儿', en: 'Take a little break' },
]

const RPS = [
  { key: 'rock', zh: '石头', en: 'Rock', icon: '✊' },
  { key: 'scissors', zh: '剪刀', en: 'Scissors', icon: '✌️' },
  { key: 'paper', zh: '布', en: 'Paper', icon: '🖐' },
] as const

/**
 * Filmy：2D 极简小跟班（Google 小恐龙那种感觉）。
 * - 模型思考时移动到中间摆思考姿势，可陪你玩石头剪刀布
 * - 点击板块/等待时给出 10 字内可爱提示
 * - 有可下载文件时跑到按钮上趴着引导
 * - 点击它会有动态反馈 + 一句问候
 */
export function Filmy({ thinking }: { thinking: boolean }) {
  const { lang } = useI18n()
  const [mood, setMood] = useState<Mood>('idle')
  const [bubble, setBubble] = useState<{ text: string; sticky?: boolean } | null>(null)
  const [rpsOpen, setRpsOpen] = useState(false)
  const [rpsResult, setRpsResult] = useState<{ me: string; bot: string; win: boolean } | null>(null)
  const [download, setDownload] = useState<DownloadAnchor | null>(null)
  const bubbleTimer = useRef<number | null>(null)
  const wasThinking = useRef(false)
  const downloadBubbleShown = useRef(false)

  const say = useCallback((zh: string, en: string, duration = 3200) => {
    if (bubbleTimer.current !== null) window.clearTimeout(bubbleTimer.current)
    setBubble({ text: lang === 'zh' ? zh : en })
    bubbleTimer.current = window.setTimeout(() => setBubble(null), duration)
  }, [lang])

  // 板块点击提示：Composer / EmptyState 会广播 filmy:say
  useEffect(() => {
    const onSay = (event: Event) => {
      const detail = (event as CustomEvent).detail as { zh?: string; en?: string } | undefined
      if (!detail) return
      say(detail.zh ?? '', detail.en ?? '', 3000)
      setMood('wave')
      window.setTimeout(() => setMood('idle'), 900)
    }
    window.addEventListener('filmy:say', onSay)
    return () => window.removeEventListener('filmy:say', onSay)
  }, [say])

  // 思考 / 完成
  useEffect(() => {
    if (thinking) {
      wasThinking.current = true
      setMood('think')
      setBubble({ text: lang === 'zh' ? '思考中…陪我玩？' : 'Thinking… play?' })
      return
    }
    if (wasThinking.current) {
      wasThinking.current = false
      setMood('idle')
      setRpsOpen(false)
      setRpsResult(null)
      say('搞定啦！', 'Done!', 2600)
    }
  }, [thinking, lang, say])

  // 有可下载文件时，跑到按钮上趴着
  useEffect(() => {
    if (thinking) return
    const scan = () => {
      const nodes = Array.from(document.querySelectorAll('[data-filmy-download]')) as HTMLElement[]
      const visible = nodes.find((el) => {
        const rect = el.getBoundingClientRect()
        return rect.width > 0 && rect.height > 0 && rect.top > 40 && rect.bottom < window.innerHeight + 20
      })
      if (!visible) {
        setDownload(null)
        downloadBubbleShown.current = false
        return
      }
      const rect = visible.getBoundingClientRect()
      setDownload({ left: rect.right - 26, top: rect.top + rect.height - 6 })
      if (!downloadBubbleShown.current) {
        downloadBubbleShown.current = true
        say('下载在这里～', 'Download here~', 2600)
      }
    }
    scan()
    const timer = window.setInterval(scan, 900)
    window.addEventListener('scroll', scan, true)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('scroll', scan, true)
    }
  }, [thinking, say])

  const onFilmyClick = () => {
    if (thinking) {
      setRpsOpen((open) => !open)
      setMood('think')
      return
    }
    if (rpsOpen) {
      setRpsOpen(false)
      return
    }
    const pick = GREETINGS[Math.floor(Math.random() * GREETINGS.length)]
    say(pick.zh, pick.en, 2600)
    setMood('wave')
    window.setTimeout(() => setMood('idle'), 900)
  }

  const playRps = (me: string) => {
    const bot = RPS[Math.floor(Math.random() * RPS.length)].key
    const win =
      (me === 'rock' && bot === 'scissors') ||
      (me === 'scissors' && bot === 'paper') ||
      (me === 'paper' && bot === 'rock')
    setRpsResult({ me, bot, win })
    setMood('wave')
    window.setTimeout(() => setMood(thinking ? 'think' : 'idle'), 700)
  }

  const rpsName = (key: string) => {
    const item = RPS.find((r) => r.key === key)
    return item ? (lang === 'zh' ? item.zh : item.en) : '?'
  }

  return (
    <div
      className={cn('filmy', 'mood-' + mood, thinking && 'thinking', download && 'on-download')}
      style={download ? { left: download.left, top: download.top, right: 'auto', bottom: 'auto' } : undefined}
    >
      {(bubble || (thinking && rpsOpen)) && (
        <div className={cn('filmy-bubble', download && 'download-bubble')} onClick={(e) => e.stopPropagation()}>
          <div className="filmy-text">{bubble?.text}</div>

          {rpsOpen && (
            <div className="filmy-rps">
              {RPS.map((item) => (
                <button key={item.key} className="filmy-rps-btn" onClick={() => playRps(item.key)} title={lang === 'zh' ? item.zh : item.en}>
                  {item.icon}
                </button>
              ))}
            </div>
          )}

          {rpsResult && (
            <div className="filmy-result">
              {lang === 'zh'
                ? '我出' + rpsName(rpsResult.bot) + '，' + (rpsResult.win ? '你赢啦！' : rpsResult.me === rpsResult.bot ? '平局～' : '我赢啦！')
                : 'I played ' + rpsName(rpsResult.bot) + ', ' + (rpsResult.win ? 'you win!' : rpsResult.me === rpsResult.bot ? 'tie~' : 'I win!')}
            </div>
          )}

          {thinking && (
            <div className="filmy-tip">
              {lang === 'zh' ? '生成完之前都可以玩' : 'Play until it finishes'}
              <button className="filmy-close" onClick={() => setRpsOpen(false)} aria-label="close">
                ×
              </button>
            </div>
          )}
        </div>
      )}

      <div className="filmy-body" onClick={onFilmyClick} role="button" aria-label={lang === 'zh' ? 'Filmy 小跟班' : 'Filmy companion'}>
        <svg viewBox="0 0 72 72" width="58" height="58" aria-hidden>
          <ellipse className="filmy-shadow" cx="36" cy="66" rx="16" ry="3.2" />
          <rect className="filmy-body-fill" x="18" y="18" width="36" height="40" rx="13" />
          <rect className="filmy-body-stroke" x="18" y="18" width="36" height="40" rx="13" />
          <circle className="filmy-eye" cx="29" cy="37" r="2.6" />
          <circle className="filmy-eye" cx="43" cy="37" r="2.6" />
          <path className="filmy-mouth" d="M31 46 Q36 50 41 46" />
          <path className="filmy-arm filmy-arm-left" d="M18 40 Q11 38 9 43" />
          <path className="filmy-arm filmy-arm-right" d="M54 40 Q61 38 63 43" />
          <path className="filmy-leg filmy-leg-left" d="M28 58 L28 63" />
          <path className="filmy-leg filmy-leg-right" d="M44 58 L44 63" />
        </svg>
        {mood === 'think' && (
          <div className="filmy-think-dots" aria-hidden>
            <span />
            <span />
            <span />
          </div>
        )}
      </div>
    </div>
  )
}
