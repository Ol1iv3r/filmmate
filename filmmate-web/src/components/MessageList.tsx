import { useEffect, useRef, useState, type WheelEvent } from 'react'
import type { UIMessage } from 'ai'
import { ArrowDown } from 'lucide-react'
import { cn } from '../lib/utils'
import { useI18n } from '../lib/i18n'
import { AssistantMessage, UserMessage } from './AssistantMessage'

/** 消息流 + 自动滚底（用户离底部较远时不打扰，显示“回到最新”）。 */
export function MessageList({
  messages,
  streaming,
  canRegenerate,
  onRegenerate,
}: {
  messages: UIMessage[]
  streaming: boolean
  canRegenerate: boolean
  onRegenerate: () => void
}) {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const lastTopRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const [showJump, setShowJump] = useState(false)

  const nearBottom = () => {
    const el = scrollRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < 56
  }

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const top = el.scrollTop
    // A deliberate scroll up must break "stick to bottom" immediately,
    // even while the page is still within the near-bottom threshold.
    if (top < lastTopRef.current - 2) stickRef.current = false
    else if (nearBottom()) stickRef.current = true
    lastTopRef.current = top
    setShowJump(!stickRef.current)
  }

  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) {
      stickRef.current = false
      setShowJump(true)
    }
  }

  const onTouchMove = () => {
    if (!nearBottom()) {
      stickRef.current = false
      setShowJump(true)
    }
  }

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (stickRef.current) {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null
        const node = scrollRef.current
        if (node) node.scrollTop = node.scrollHeight
      })
    } else {
      setShowJump(true)
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [messages, streaming])

  const jumpToBottom = () => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stickRef.current = true
    setShowJump(false)
  }

  return (
    <div
      className="chat-scroll"
      ref={scrollRef}
      onScroll={onScroll}
      onWheel={onWheel}
      onTouchMove={onTouchMove}
    >
      <div className="chat-inner">
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1
          if (m.role === 'user') return <UserMessage key={m.id} message={m} />
          return (
            <AssistantMessage
              key={m.id}
              message={m}
              streaming={streaming && isLast}
              canRegenerate={canRegenerate && isLast}
              onRegenerate={onRegenerate}
            />
          )
        })}
      </div>
      <button className={cn('jump-bottom', showJump && 'show')} onClick={jumpToBottom}>
        <ArrowDown size={14} />
        {t('回到最新', 'Back to latest')}
      </button>
    </div>
  )
}

/** 会话加载骨架屏。 */
export function MessageSkeleton() {
  return (
    <div className="chat-inner skeleton-wrap">
      <div className="skel-bubble user" />
      <div className="skel-row">
        <div className="skel-avatar" />
        <div className="skel-bubble assistant" style={{ width: '72%' }} />
      </div>
      <div className="skel-row">
        <div className="skel-avatar" />
        <div className="skel-bubble assistant" style={{ width: '46%' }} />
      </div>
      <div className="skel-card" />
    </div>
  )
}
