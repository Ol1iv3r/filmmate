import { useEffect, useRef, useState } from 'react'
import type { UIMessage } from 'ai'
import { ArrowDown } from 'lucide-react'
import { cn } from '../lib/utils'
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const [showJump, setShowJump] = useState(false)

  const nearBottom = () => {
    const el = scrollRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < 140
  }

  const onScroll = () => {
    const near = nearBottom()
    stickRef.current = near
    setShowJump(!near)
  }

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (stickRef.current || streaming) {
      el.scrollTop = el.scrollHeight
    } else {
      setShowJump(true)
    }
  }, [messages, streaming])

  const jumpToBottom = () => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    stickRef.current = true
    setShowJump(false)
  }

  return (
    <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
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
        回到最新
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
