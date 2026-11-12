import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '@ai-sdk/react'
import type { ChatTransport, UIMessage } from 'ai'
import { createTransport } from '../lib/transport'
import { createRepository, titleFromMessages, type ConversationRepository } from '../lib/conversations'
import { MessageList, MessageSkeleton } from './MessageList'
import { Composer, type ComposerHandle } from './Composer'
import { EmptyState } from './EmptyState'
import { ErrorBanner } from './ErrorBanner'

/**
 * 聊天面板：一个会话 = 一个 useChat 实例（key 重挂载保证状态隔离）。
 * messages 变化 → 自动落盘（debounce）到 ConversationRepository。
 */
export function ChatPanel({
  conversationId,
  onAutoTitle,
}: {
  conversationId: string
  onAutoTitle: (id: string, title: string) => void
}) {
  const repository = useMemo<ConversationRepository>(() => createRepository(), [])
  const transportRef = useRef<ChatTransport<UIMessage> | null>(null)
  if (transportRef.current === null) transportRef.current = createTransport()

  const [initial, setInitial] = useState<UIMessage[] | null>(null)

  useEffect(() => {
    let cancelled = false
    setInitial(null)
    repository
      .load(conversationId)
      .then((m) => {
        if (!cancelled) setInitial(m ?? [])
      })
      .catch(() => {
        if (!cancelled) setInitial([])
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, repository])

  if (initial === null) {
    return (
      <div className="chat-panel">
        <MessageSkeleton />
      </div>
    )
  }

  return (
    <ChatInner
      key={conversationId}
      conversationId={conversationId}
      repository={repository}
      transport={transportRef.current}
      initial={initial}
      onAutoTitle={onAutoTitle}
    />
  )
}

function textOfUser(m: UIMessage): string {
  return m.parts
    .filter((p) => p.type === 'text')
    .map((p) => p.text)
    .join('\n')
}

function ChatInner({
  conversationId,
  repository,
  transport,
  initial,
  onAutoTitle,
}: {
  conversationId: string
  repository: ConversationRepository
  transport: ChatTransport<UIMessage>
  initial: UIMessage[]
  onAutoTitle: (id: string, title: string) => void
}) {
  const chat = useChat({ id: conversationId, transport, messages: initial })
  const { messages, status, error, sendMessage, regenerate, stop, clearError } = chat
  const streaming = status === 'submitted' || status === 'streaming'

  const [composerText, setComposerText] = useState('')
  const composerRef = useRef<ComposerHandle>(null)
  const lastUserRef = useRef('')

  const handlePickExample = useCallback((prompt: string) => {
    composerRef.current?.fill(prompt)
  }, [])

  const lastUser = useMemo(
    () => [...messages].reverse().find((m) => m.role === 'user'),
    [messages],
  )

  // 自动起标题（只在「新对话」时覆盖，用户手动改名后不再动）
  useEffect(() => {
    if (messages.length === 0) return
    onAutoTitle(conversationId, titleFromMessages(messages))
  }, [messages.length === 0 ? 0 : messages[0]?.id, conversationId, onAutoTitle]) // eslint-disable-line react-hooks/exhaustive-deps

  // 落盘（debounce；ready/error 时立刻落一次）
  useEffect(() => {
    if (messages.length === 0) return
    const t = window.setTimeout(() => {
      void repository.save(conversationId, messages)
    }, 500)
    return () => window.clearTimeout(t)
  }, [messages, conversationId, repository])

  useEffect(() => {
    if (messages.length === 0) return
    if (status === 'ready' || status === 'error') {
      void repository.save(conversationId, messages)
    }
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = useCallback(
    (text: string) => {
      lastUserRef.current = text
      sendMessage({ text })
    },
    [sendMessage],
  )

  const handleRetry = useCallback(() => {
    clearError()
    const last = messages[messages.length - 1]
    if (last && last.role === 'assistant') {
      regenerate()
    } else {
      const fallback = lastUser ? textOfUser(lastUser) : lastUserRef.current
      if (fallback.trim()) sendMessage({ text: fallback })
    }
  }, [clearError, messages, lastUser, regenerate, sendMessage])

  const canRegenerate = status === 'ready' && messages.some((m) => m.role === 'user')
  const showEmpty = messages.length === 0 && !streaming

  return (
    <div className="chat-panel">
      {showEmpty ? (
        <div className="chat-scroll">
          <EmptyState onPick={handlePickExample} />
        </div>
      ) : (
        <MessageList
          messages={messages}
          streaming={streaming}
          canRegenerate={canRegenerate}
          onRegenerate={regenerate}
        />
      )}

      {error && <ErrorBanner message={error.message} onRetry={handleRetry} onDismiss={clearError} />}

      <Composer
        ref={composerRef}
        value={composerText}
        onChange={setComposerText}
        streaming={streaming}
        onSend={handleSend}
        onStop={stop}
      />
    </div>
  )
}
