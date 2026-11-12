/**
 * Transport 选择器：
 *  - VITE_API_BASE 有值 → DefaultChatTransport 连 Jacky 的 AI SDK 后端
 *    （POST {base}/api/chat，标准 UIMessageStream 协议）
 *  - 无值 → MockTransport（本地流式 + 模拟 tool-call，独立可演示）
 *
 * 两个 transport 输出同构的 UIMessageChunk 流，渲染层零改动。
 */
import { DefaultChatTransport, type ChatTransport, type UIMessage } from 'ai'
import { buildPlan, buildSteps, streamFromSteps } from '../mock/mockEngine'

export const API_BASE: string | undefined = import.meta.env.VITE_API_BASE || undefined

export const isMockMode = !API_BASE

class MockTransport implements ChatTransport<UIMessage> {
  sendMessages(options: {
    trigger: 'submit-message' | 'regenerate-message'
    messages: UIMessage[]
    abortSignal: AbortSignal | undefined
  }): Promise<ReadableStream<import('ai').UIMessageChunk>> {
    const lastUser = [...options.messages].reverse().find((m) => m.role === 'user')
    const text = lastUser?.parts
      .filter((p) => p.type === 'text')
      .map((p) => p.text)
      .join('\n')
    const plan = buildPlan(text ?? '')
    const steps = buildSteps(plan)
    return Promise.resolve(streamFromSteps(steps, options.abortSignal))
  }

  reconnectToStream(): Promise<null> {
    return Promise.resolve(null)
  }
}

export function createTransport(): ChatTransport<UIMessage> {
  if (API_BASE) {
    return new DefaultChatTransport<UIMessage>({
      api: `${API_BASE.replace(/\/$/, '')}/api/chat`,
    })
  }
  return new MockTransport()
}
