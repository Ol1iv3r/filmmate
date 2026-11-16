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

const SIZE_W = 78
const SIZE_H = 100
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
  return { left: Math.max(8, w - 108), top: Math.max(8, h - 300), mode: 'idle', side: 'right' }
}

/** Filmy：会走路、会摆表情的 2D 小跟班。 */
export function Filmy({ thinking }: { thinking: boolean }) {
  const { lang } = useI18n()
  const [target, setTarget] = useState<Target>(defaultTarget)
  const [moving, setMoving] = useState(false)
  const [expression, setExpression] = useState<Expression>('idle')
  const [bubble, setBubble] = useState<string | null>(null)
  const [rpsOpen, setRpsOpen] = useState(false)
  const [rpsResult, setRpsResult] = useState<RpsResult | null>(null)
  const [walkSide, setWalkSide] = useState<'left' | 'right'>('right')

  const targetRef = useRef<Target>(defaultTarget())
  const movingTimer = useRef<number | null>(null)
  const bubbleTimer = useRef<number | null>(null)
  const expressionTimer = useRef<number | null>(null)
  const thinkingRef = useRef(thinking)
  const rpsOpenRef = useRef(false)

  thinkingRef.current = thinking
  rpsOpenRef.current = rpsOpen

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
      const left = Math.max(8, Math.min(w - SIZE_W - 8, Math.round(r.left - 46)))
      return {
        left,
        top: Math.max(8, Math.round(r.top - 58)),
        mode: 'download',
        side: r.left + r.width / 2 > w / 2 ? 'right' : 'left',
      }
    }
    return { left: Math.max(8, w - 108), top: Math.max(8, h - 300), mode: 'idle', side: 'right' }
  }, [])

  const applyTarget = useCallback((next: Target, immediate = false) => {
    const prev = targetRef.current
    const changed = prev.left !== next.left || prev.top !== next.top || prev.mode !== next.mode
    if (!changed) return
    targetRef.current = next
    if (next.mode === 'download') setWalkSide(next.side === 'right' ? 'right' : 'left')
    if (immediate) {
      setTarget(next)
      return
    }
    setTarget(next)
    setMoving(true)
    if (movingTimer.current !== null) window.clearTimeout(movingTimer.current)
    movingTimer.current = window.setTimeout(() => {
      setMoving(false)
      if (next.mode === 'download') setExpressionFor('happy', 1600)
      else if (!thinkingRef.current) setExpressionFor('idle')
    }, WALK_MS)
  }, [setExpressionFor])

  // 初始定位 + 尺寸/滚动/定时扫描
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

  // 思考状态：走到中间、摆思考表情；结束后恢复
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
    switch (expression) {
      case 'happy':
      case 'win':
        return <path d="M30 45 Q38 53 46 45" fill="none" stroke="#20232b" strokeWidth="2.4" strokeLinecap="round" />
      case 'lose':
        return <path d="M31 48 Q38 42 45 48" fill="none" stroke="#20232b" strokeWidth="2.4" strokeLinecap="round" />
      case 'tie':
        return <path d="M31 46 Q35 49 38 46 Q41 43 45 46" fill="none" stroke="#20232b" strokeWidth="2.2" strokeLinecap="round" />
      case 'think':
        return <ellipse cx="38" cy="46" rx="3.2" ry="2.6" fill="#20232b" />
      default:
        return <path d="M32 45 Q38 49 44 45" fill="none" stroke="#20232b" strokeWidth="2.2" strokeLinecap="round" />
    }
  }

  // 眼睛（带高光/表情）
  const eyesFor = () => {
    if (expression === 'win') {
      return (
        <>
          <path d="M23 34 L26 31 L29 34 L26 37 Z" fill="#20232b" />
          <path d="M47 34 L50 31 L53 34 L50 37 Z" fill="#20232b" />
        </>
      )
    }
    if (expression === 'lose') {
      return (
        <>
          <path d="M23 33 Q26 36 29 33" fill="none" stroke="#20232b" strokeWidth="2" strokeLinecap="round" />
          <path d="M47 33 Q50 36 53 33" fill="none" stroke="#20232b" strokeWidth="2" strokeLinecap="round" />
        </>
      )
    }
    return (
      <>
        <circle cx="26" cy="34" r="4.6" fill="#fff8ea" />
        <circle cx="50" cy="34" r="4.6" fill="#fff8ea" />
        <circle
          cx={expression === 'think' ? 27.4 : expression === 'tie' ? 27 : 26}
          cy={expression === 'think' ? 33 : 34}
          r="2.6"
          fill="#20232b"
        />
        <circle
          cx={expression === 'think' ? 51.4 : expression === 'tie' ? 51 : 50}
          cy={expression === 'think' ? 33 : 34}
          r="2.6"
          fill="#20232b"
        />
        <circle cx={expression === 'think' ? 28.2 : 26.9} cy={expression === 'think' ? 32.2 : 33.2} r=".8" fill="#fff" />
        <circle cx={expression === 'think' ? 52.2 : 50.9} cy={expression === 'think' ? 32.2 : 33.2} r=".8" fill="#fff" />
      </>
    )
  }

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
          <svg viewBox="0 0 76 100" width="72" height="94" aria-hidden>
            <ellipse className="filmy-shadow" cx="38" cy="95" rx="17" ry="3" />

            {/* 腿 + 鞋（走路时交替） */}
            <g className="filmy-legs">
              <path className="filmy-leg filmy-leg-a" d="M28 78 L28 88" />
              <path className="filmy-leg filmy-leg-b" d="M48 78 L48 88" />
              <ellipse className="filmy-shoe filmy-shoe-a" cx="28" cy="90" rx="5" ry="2.6" />
              <ellipse className="filmy-shoe filmy-shoe-b" cx="48" cy="90" rx="5" ry="2.6" />
            </g>

            {/* 身体 */}
            <rect className="filmy-torso" x="20" y="58" width="36" height="24" rx="12" />
            {/* 手 */}
            <path className="filmy-hand filmy-hand-left" d="M21 68 Q12 70 11 76" />
            <path className={cn('filmy-hand', 'filmy-hand-right', target.mode === 'download' && !moving && 'arm-point')} d="M55 68 Q64 70 66 76" />

            {/* 天线 */}
            <path className="filmy-antenna" d="M38 12 L38 4" />
            <circle className="filmy-antenna-dot" cx="38" cy="3.2" r="2.6" />

            {/* 头 */}
            <rect className="filmy-head" x="14" y="14" width="48" height="44" rx="20" />
            <circle className="filmy-ear" cx="13" cy="34" r="5" />
            <circle className="filmy-ear" cx="63" cy="34" r="5" />
            <ellipse className="filmy-blush" cx="19" cy="43" rx="4" ry="2.3" />
            <ellipse className="filmy-blush" cx="57" cy="43" rx="4" ry="2.3" />
            {eyesFor()}
            {mouthFor()}
            {expression === 'think' && (
              <circle className="filmy-thought" cx="58" cy="15" r="2.2" />
            )}
          </svg>
        </div>
      </div>

      {rpsOpen && thinking && (
        <div className="filmy-rps-layer" onClick={(e) => e.stopPropagation()}>
          <div className="filmy-rps-buttons">
            {RPS.map((item) => (
              <button
                key={item.key}
                className={cn('filmy-rps-btn', rpsResult?.me === item.key && 'chosen')}
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
