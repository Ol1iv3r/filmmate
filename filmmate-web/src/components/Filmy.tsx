import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { cn } from '../lib/utils'

type Mode = 'idle' | 'think' | 'download'
type Expression = 'idle' | 'happy' | 'think' | 'win' | 'lose' | 'tie'

interface Target {
  left: number
  top: number
  mode: Mode
  side: 'left' | 'right'
}

interface RpsResult {
  me: string
  bot: string
  outcome: 'win' | 'lose' | 'tie'
}

const SIZE_W = 76
const SIZE_H = 96
const WALK_MS = 1150

const GREETINGS = [
  { zh: '嗨～我是 Filmy', en: 'Hi, I am Filmy' },
  { zh: '今天拍什么？', en: 'What to shoot?' },
  { zh: '陪你一起想～', en: 'Thinking with you~' },
  { zh: '加油鸭！', en: 'You got this!' },
]

const RPS = [
  { key: 'rock', zh: '石头', en: 'Rock', icon: '✊' },
  { key: 'scissors', zh: '剪刀', en: 'Scissors', icon: '✌️' },
  { key: 'paper', zh: '布', en: 'Paper', icon: '🖐' },
] as const

function defaultTarget(): Target {
  const w = typeof window === 'undefined' ? 1200 : window.innerWidth
  const h = typeof window === 'undefined' ? 800 : window.innerHeight
  return { left: Math.max(8, w - 104), top: Math.max(8, h - 300), mode: 'idle', side: 'right' }
}

/** Filmy：参考黄色方块小人设计的 2D 极简小跟班。 */
export function Filmy({ thinking }: { thinking: boolean }) {
  const { lang } = useI18n()
  const [target, setTarget] = useState<Target>(defaultTarget)
  const [moving, setMoving] = useState(false)
  const [expression, setExpression] = useState<Expression>('idle')
  const [bubble, setBubble] = useState<string | null>(null)
  const [rpsOpen, setRpsOpen] = useState(false)
  const [rpsResult, setRpsResult] = useState<RpsResult | null>(null)

  const targetRef = useRef<Target>(defaultTarget())
  const movingTimer = useRef<number | null>(null)
  const bubbleTimer = useRef<number | null>(null)
  const expressionTimer = useRef<number | null>(null)
  const thinkingRef = useRef(thinking)

  thinkingRef.current = thinking

  const setExpressionFor = useCallback((next: Expression, ms = 0) => {
    setExpression(next)
    if (expressionTimer.current !== null) window.clearTimeout(expressionTimer.current)
    if (ms > 0) {
      expressionTimer.current = window.setTimeout(() => {
        setExpression(thinkingRef.current ? 'think' : 'idle')
      }, ms)
    }
  }, [])

  const say = useCallback((text: string, ms = 2600) => {
    if (bubbleTimer.current !== null) window.clearTimeout(bubbleTimer.current)
    setBubble(text)
    bubbleTimer.current = window.setTimeout(() => setBubble(null), ms)
  }, [])

  const computeTarget = useCallback((): Target => {
    const w = window.innerWidth
    const h = window.innerHeight
    if (thinkingRef.current) {
      // 和正在生成的 assistant 消息头像待在一起
      const avatars = Array.from(document.querySelectorAll('.msg.assistant .msg-avatar')) as HTMLElement[]
      const anchor = avatars[avatars.length - 1]
      if (anchor) {
        const r = anchor.getBoundingClientRect()
        return {
          left: Math.max(8, Math.min(w - SIZE_W - 8, Math.round(r.left - SIZE_W - 6))),
          top: Math.max(8, Math.round(r.top - 22)),
          mode: 'think',
          side: 'right',
        }
      }
      return {
        left: Math.max(8, Math.round(w / 2 - SIZE_W / 2)),
        top: Math.max(8, Math.round(h - 336)),
        mode: 'think',
        side: 'right',
      }
    }
    const nodes = Array.from(document.querySelectorAll('[data-filmy-download]')) as HTMLElement[]
    const visible = nodes.find((el) => {
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0 && r.top > 60 && r.bottom < h + 40
    })
    if (visible) {
      const r = visible.getBoundingClientRect()
      const left = Math.max(8, Math.min(w - SIZE_W - 8, Math.round(r.left - 44)))
      return {
        left,
        top: Math.max(8, Math.round(r.top - 54)),
        mode: 'download',
        side: r.left + r.width / 2 > w / 2 ? 'right' : 'left',
      }
    }
    return { left: Math.max(8, w - 104), top: Math.max(8, h - 300), mode: 'idle', side: 'right' }
  }, [])

  const applyTarget = useCallback((next: Target, immediate = false) => {
    const prev = targetRef.current
    const changed = prev.left !== next.left || prev.top !== next.top || prev.mode !== next.mode
    if (!changed) return
    targetRef.current = next
    setTarget(next)
    if (immediate) return
    setMoving(true)
    if (movingTimer.current !== null) window.clearTimeout(movingTimer.current)
    movingTimer.current = window.setTimeout(() => {
      setMoving(false)
      if (next.mode === 'download') setExpressionFor('happy', 1600)
      else if (!thinkingRef.current) setExpressionFor('idle')
    }, WALK_MS)
  }, [setExpressionFor])

  useEffect(() => {
    applyTarget(computeTarget(), true)
    const update = () => applyTarget(computeTarget())
    update()
    const timer = window.setInterval(update, 700)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [applyTarget, computeTarget])

  useEffect(() => {
    if (thinking) {
      setExpression('think')
      setRpsOpen(false)
      setRpsResult(null)
      applyTarget(computeTarget())
      return
    }
    setRpsOpen(false)
    setRpsResult(null)
    setExpressionFor('idle')
    applyTarget(computeTarget())
  }, [thinking, applyTarget, computeTarget, setExpressionFor])

  const onAvatarClick = () => {
    if (thinking) {
      setRpsOpen((open) => !open)
      if (!rpsOpen) setExpression('think')
      return
    }
    if (rpsOpen) {
      setRpsOpen(false)
      return
    }
    const pick = GREETINGS[Math.floor(Math.random() * GREETINGS.length)]
    say(lang === 'zh' ? pick.zh : pick.en)
    setExpressionFor('happy', 1500)
  }

  const playRps = (me: string) => {
    const bot = RPS[Math.floor(Math.random() * RPS.length)].key
    const outcome: RpsResult['outcome'] =
      me === bot ? 'tie' : (me === 'rock' && bot === 'scissors') || (me === 'scissors' && bot === 'paper') || (me === 'paper' && bot === 'rock') ? 'win' : 'lose'
    setRpsResult({ me, bot, outcome })
    setExpressionFor(outcome === 'win' ? 'win' : outcome === 'lose' ? 'lose' : 'tie', 0)
  }

  const rpsName = (key: string) => {
    const item = RPS.find((r) => r.key === key)
    return item ? (lang === 'zh' ? item.zh : item.en) : '?'
  }

  const mouthFor = () => {
    if (expression === 'lose') {
      return <path d="M29 50 Q38 42 47 50" fill="none" stroke="#20232b" strokeWidth="3.6" strokeLinecap="round" />
    }
    if (expression === 'tie') {
      return <path d="M29 47 Q33.5 51 38 47 Q42.5 43 47 47" fill="none" stroke="#20232b" strokeWidth="3" strokeLinecap="round" />
    }
    if (expression === 'think') {
      return <ellipse cx="38" cy="48" rx="3.4" ry="2.8" fill="#20232b" />
    }
    return (
      <path
        d={expression === 'win' || expression === 'happy' ? 'M29 45 Q38 56 47 45' : 'M30 45 Q38 52 46 45'}
        fill="none"
        stroke="#20232b"
        strokeWidth="3.6"
        strokeLinecap="round"
      />
    )
  }

  const eyeOffsetY = expression === 'think' ? -2 : expression === 'lose' ? 1.5 : 0

  return (
    <>
      <div
        className={cn(
          'filmy filmy-v2',
          'filmy-mode-' + target.mode,
          moving && 'is-walking',
          target.mode === 'download' && !moving && 'is-pointing',
          target.side === 'left' && 'point-left',
        )}
        style={{ left: target.left, top: target.top }}
      >
        {bubble && (
          <div className="filmy-say">
            {bubble}
            <span className="filmy-say-tail" />
          </div>
        )}

        <div className={cn('filmy-avatar', 'expr-' + expression)} onClick={onAvatarClick} role="button" aria-label="Filmy">
          {target.mode === 'download' && !moving && (
            <span className={cn('filmy-pointer', target.side === 'left' ? 'to-left' : 'to-right')} aria-hidden>
              ◀
            </span>
          )}
          <svg viewBox="0 0 76 100" width="70" height="92" aria-hidden>
            <ellipse className="filmy-shadow" cx="38" cy="95" rx="15" ry="2.8" />

            {/* 腿：两条黄色小短腿，无脚 */}
            <g className="filmy-legs">
              <rect className="filmy-leg filmy-leg-a" x="27" y="72" width="9" height="20" rx="4.5" />
              <rect className="filmy-leg filmy-leg-b" x="41" y="72" width="9" height="20" rx="4.5" />
            </g>

            {/* 黑色三撮头发 */}
            <g className="filmy-hair">
              <path d="M22 26 Q18 8 31 5 Q26 14 31 26" />
              <path d="M33 26 Q34 7 47 6 Q38 14 42 26" />
              <path d="M44 26 Q52 10 57 20 Q52 22 50 26" />
            </g>

            {/* 黄色方块身体 */}
            <rect className="filmy-body" x="13" y="24" width="50" height="50" rx="11" />

            {/* 眼睛：白底 + 黑色 S 形瞳孔 */}
            <g className="filmy-eyes">
              <ellipse className="filmy-eye-white" cx="27" cy="44" rx="7" ry="9" />
              <ellipse className="filmy-eye-white" cx="49" cy="44" rx="7" ry="9" />
              <path
                className="filmy-pupil"
                transform={'translate(0 ' + eyeOffsetY + ')'}
                d="M24 40 Q31 39 31 44 Q31 49 25 48 Q28 46 28 44 Q28 42 24 40 Z"
              />
              <path
                className="filmy-pupil"
                transform={'translate(0 ' + eyeOffsetY + ')'}
                d="M46 40 Q53 39 53 44 Q53 49 47 48 Q50 46 50 44 Q50 42 46 40 Z"
              />
            </g>

            {/* 腮红 */}
            <circle className="filmy-blush" cx="18" cy="53" r="4.4" />
            <circle className="filmy-blush" cx="58" cy="53" r="4.4" />

            {mouthFor()}
          </svg>
        </div>
      </div>

      {rpsOpen && thinking && (
        <div
          className="filmy-rps-layer filmy-rps-v2"
          style={{ left: target.left + SIZE_W / 2, top: Math.max(70, target.top - 76) }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="filmy-rps-buttons">
            {RPS.map((item, i) => (
              <button
                key={item.key}
                className={cn('filmy-rps-btn', rpsResult?.me === item.key && 'chosen')}
                style={{ animationDelay: (i * 70) + 'ms' }}
                onClick={() => playRps(item.key)}
                title={lang === 'zh' ? item.zh : item.en}
              >
                {item.icon}
              </button>
            ))}
          </div>
          {rpsResult && (
            <div className="filmy-rps-result">
              {lang === 'zh'
                ? 'Filmy 出了 ' + RPS.find((r) => r.key === rpsResult.bot)?.icon + ' ' + rpsName(rpsResult.bot) + ' · ' +
                  (rpsResult.outcome === 'win' ? '你赢啦' : rpsResult.outcome === 'lose' ? '我赢啦' : '平局')
                : 'Filmy played ' + rpsName(rpsResult.bot) + ' · ' +
                  (rpsResult.outcome === 'win' ? 'you win' : rpsResult.outcome === 'lose' ? 'I win' : 'tie')}
            </div>
          )}
        </div>
      )}
    </>
  )
}
