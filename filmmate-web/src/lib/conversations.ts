/**
 * 会话存取接口（Phase 3 的存储 API 是 Jacky 的，列表 UI 是我们的）。
 *
 * - LocalStorageRepository：浏览器本地存储（现在就能跑，不依赖后端）
 * - RemoteRepository：走 {VITE_API_BASE}/api/conversations 的 REST 接口
 *   （Jacky Phase 3 落地后，设置 VITE_REMOTE_CONVERSATIONS=1 即切换，UI 零改动）
 *
 * 注意：UIMessage 本身就是可 JSON 序列化的纯数据，
 * 与 Jacky 计划中「LangChain message → dict → JSON 落盘」的做法一一对应。
 */
import type { UIMessage } from 'ai'
import { API_BASE } from './transport'

export interface ConversationMeta {
  id: string
  title: string
  createdAt: number
  updatedAt: number
}

export interface ConversationRepository {
  list(): Promise<ConversationMeta[]>
  load(id: string): Promise<UIMessage[] | null>
  /** 保存消息并更新 updatedAt；title 传了才覆盖（自动起标题用）。 */
  save(id: string, messages: UIMessage[], title?: string): Promise<ConversationMeta>
  rename(id: string, title: string): Promise<void>
  remove(id: string): Promise<void>
}

const KEY_INDEX = 'filmmate:conversations:v1'
const KEY_PREFIX = 'filmmate:conv:v1:'

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 存储满/隐私模式：静默降级，不影响对话 */
  }
}

/** 从第一条用户消息生成会话标题。 */
export function titleFromMessages(messages: UIMessage[], fallback = '新对话'): string {
  const first = messages.find((m) => m.role === 'user')
  if (!first) return fallback
  const text = first.parts
    .filter((p) => p.type === 'text')
    .map((p) => p.text)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return fallback
  return text.length > 24 ? `${text.slice(0, 24)}…` : text
}

export class LocalStorageRepository implements ConversationRepository {
  private index(): ConversationMeta[] {
    return readJson<ConversationMeta[]>(KEY_INDEX, [])
  }

  async list(): Promise<ConversationMeta[]> {
    return this.index().sort((a, b) => b.updatedAt - a.updatedAt)
  }

  async load(id: string): Promise<UIMessage[] | null> {
    const raw = localStorage.getItem(KEY_PREFIX + id)
    if (raw === null) return null
    try {
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? (parsed as UIMessage[]) : null
    } catch {
      return null
    }
  }

  async save(id: string, messages: UIMessage[], title?: string): Promise<ConversationMeta> {
    const now = Date.now()
    const list = this.index()
    const existing = list.find((c) => c.id === id)
    const meta: ConversationMeta = existing ?? {
      id,
      title: title ?? titleFromMessages(messages),
      createdAt: now,
      updatedAt: now,
    }
    if (title !== undefined && title.trim()) meta.title = title.trim()
    else if (!existing || meta.title === '新对话') meta.title = titleFromMessages(messages, meta.title)
    meta.updatedAt = now
    writeJson(KEY_PREFIX + id, messages)
    writeJson(KEY_INDEX, existing ? list.map((c) => (c.id === id ? meta : c)) : [meta, ...list])
    return meta
  }

  async rename(id: string, title: string): Promise<void> {
    const list = this.index()
    const meta = list.find((c) => c.id === id)
    if (meta) {
      meta.title = title
      meta.updatedAt = Date.now()
      writeJson(KEY_INDEX, list)
    }
  }

  async remove(id: string): Promise<void> {
    localStorage.removeItem(KEY_PREFIX + id)
    writeJson(KEY_INDEX, this.index().filter((c) => c.id !== id))
  }
}

/** Jacky Phase 3 的远端接口（启用后自动切换）。约定见 docs/CONTRACT.md。 */
export class RemoteRepository implements ConversationRepository {
  constructor(private base: string) {}

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
    if (!res.ok) throw new Error(`conversations api ${res.status}`)
    return res.json() as Promise<T>
  }

  list(): Promise<ConversationMeta[]> {
    return this.req('/api/conversations')
  }
  async load(id: string): Promise<UIMessage[] | null> {
    const res = await fetch(`${this.base}/api/conversations/${id}`)
    if (res.status === 404) return null
    if (!res.ok) throw new Error(`conversations api ${res.status}`)
    const data = (await res.json()) as { messages?: UIMessage[] }
    return data.messages ?? null
  }
  save(id: string, messages: UIMessage[], title?: string): Promise<ConversationMeta> {
    return this.req(`/api/conversations/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ messages, title }),
    })
  }
  rename(id: string, title: string): Promise<void> {
    return this.req(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
  }
  remove(id: string): Promise<void> {
    return this.req(`/api/conversations/${id}`, { method: 'DELETE' })
  }
}

export function createRepository(): ConversationRepository {
  const base = API_BASE?.replace(/\/$/, '')
  const remote = import.meta.env.VITE_REMOTE_CONVERSATIONS === '1' || import.meta.env.VITE_REMOTE_CONVERSATIONS === 'true'
  if (remote && base !== undefined) return new RemoteRepository(base)
  return new LocalStorageRepository()
}
