/**
 * Transport 选择器：
 *  - 由 FastAPI 提供页面时，直接连接同源 API。
 *  - 独立开发时可配置 VITE_API_BASE，留空则演示 MockTransport。
 *
 * 两个 transport 输出同构的 UIMessageChunk 流，渲染层零改动。
 */
import { DefaultChatTransport, type ChatTransport, type UIMessage } from 'ai'
import { buildPlan, buildSteps, streamFromSteps } from '../mock/mockEngine'

export const API_BASE: string | undefined = document.querySelector('meta[name="filmmate-backend"]')
  ? ''
  : import.meta.env.VITE_API_BASE || undefined

export const isMockMode = API_BASE === undefined

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
  if (API_BASE !== undefined) {
    return new DefaultChatTransport<UIMessage>({
      api: `${API_BASE.replace(/\/$/, '')}/api/chat`,
    })
  }
  return new MockTransport()
}
