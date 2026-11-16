import { useRef, useState } from 'react'
import type { UIMessage } from 'ai'
import { Volume2, Square, Copy, Check, RefreshCw } from 'lucide-react'
import { messageToViews, type UiPartView } from '../lib/contract'
import { cn, copyText, speak, stopSpeaking, stripMarkdown } from '../lib/utils'
import { Markdown } from './Markdown'
import { ToolCard } from './parts/ToolCard'
import { ReasoningBlock } from './parts/ReasoningBlock'

/**
 * 一条 assistant 消息：text / tool-call / reasoning 混排。
 * 多个工具调用按时间线排列（竖线 + 圆点）。
 */
export function AssistantMessage({
  message,
  streaming,
  canRegenerate,
  onRegenerate,
}: {
  message: UIMessage
  streaming: boolean
  canRegenerate: boolean
  onRegenerate: () => void
}) {
  const views = messageToViews(message)
  // 板块（工具结果卡片）统一放到回答文字之后
  const orderedViews = [
    ...views.filter((v) => v.kind === 'text'),
    ...views.filter((v) => v.kind !== 'text'),
  ]
  const firstSeen = useRef(new Map<string, number>())
  const finishSeen = useRef(new Map<string, number>())
  const [speaking, setSpeaking] = useState(false)
  const [copied, setCopied] = useState(false)

  const now = Date.now()
  const seenAt = (key: string) => {
    if (!firstSeen.current.has(key)) firstSeen.current.set(key, now)
    return firstSeen.current.get(key)!
  }
  /** 后端没给 ms 时，用「第一次进入完成态的观测时间」兜底。 */
  const doneAt = (key: string, done: boolean) => {
    if (!done) return undefined
    if (!finishSeen.current.has(key)) finishSeen.current.set(key, now)
    return finishSeen.current.get(key)
  }

  const plainText = () =>
    views
      .filter((v) => v.kind === 'text')
      .map((v) => (v as Extract<UiPartView, { kind: 'text' }>).text)
      .join('\n')

  const onSpeak = () => {
    if (speaking) {
      stopSpeaking()
      setSpeaking(false)
      return
    }
    const text = plainText()
    if (!text) return
    setSpeaking(true)
    const u = speak(text)
    if (u) {
      u.onend = () => setSpeaking(false)
      u.onerror = () => setSpeaking(false)
    } else {
      setSpeaking(false)
    }
  }

  const onCopy = async () => {
    const text = plainText()
    if (!text || !(await copyText(text))) return
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="msg assistant">
      <div className="msg-avatar">🎬</div>
      <div className="msg-body">
        <div className="assistant-parts">
          {orderedViews.map((v, i) => {
            if (v.kind === 'text') {
              return <Markdown key={i} text={v.text} />
            }
            if (v.kind === 'reasoning') {
              return <ReasoningBlock key={i} text={v.text} />
            }
            const activity = v.activity
            const key = activity.callId || `${activity.toolName}-${i}`
            return (
              <ToolCard
                key={`${key}-${i}`}
                activity={activity}
                firstSeenAt={seenAt(key)}
                doneAtFallback={doneAt(key, activity.state !== 'running')}
                isLast={i === orderedViews.length - 1}
              />
            )
          })}
          {streaming && <span className="stream-cursor" aria-hidden />}
        </div>

        {!streaming && (
          <div className="msg-actions">
            <button className="icon-btn mini" onClick={onSpeak} title={speaking ? '停止朗读' : '朗读回答'}>
              {speaking ? <Square size={13} /> : <Volume2 size={13} />}
            </button>
            <button className="icon-btn mini" onClick={onCopy} title="复制回答">
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
            {canRegenerate && (
              <button className="icon-btn mini" onClick={onRegenerate} title="重新生成">
                <RefreshCw size={13} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export function UserMessage({ message }: { message: UIMessage }) {
  const text = message.parts
    .filter((p) => p.type === 'text')
    .map((p) => p.text)
    .join('\n')
  return (
    <div className={cn('msg user')}>
      <div className="user-bubble">{text}</div>
    </div>
  )
}
