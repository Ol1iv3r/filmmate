/**
 * ─────────────────────────────────────────────────────────────────────────────
 * 契约层 contract.ts —— 前端与 Jacky 的后端 / 未来任何后端对齐的唯一协议文件
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * 兼容目标（两个来源，都能直接渲染，不需要后端改动）：
 *
 *   A. Vercel AI SDK v5+ 官方协议（`ai` / `@ai-sdk/react` 的 UIMessage 流）
 *      - 文本：{ type: 'text', text }
 *      - 工具：{ type: 'tool-<toolName>', toolCallId, state, input, output,
 *                inputText, outputText, errorText }
 *      - 动态工具：{ type: 'dynamic-tool', toolName, toolCallId, state, ... }
 *      - 思考：{ type: 'reasoning', text }
 *
 *   B. 《团队项目说明》§4.2 的旧版 Part 结构（文档里 Oliver 与 Jacky 定的）
 *      - { type: 'tool-call',  toolCallId, toolName, input }
 *      - { type: 'tool-result', toolCallId, toolName, output }
 *      同 toolCallId 的 call/result 会被合并成一张工具卡片。
 *
 * 渲染层只消费本文件导出的「视图模型」UiPartView，与协议细节解耦。
 * Jacky 那边的 message → dict → JSON 落盘完全兼容：UIMessage 本身就是
 * 可 JSON 序列化的纯数据（LangChain 的 message dict 也可以直接转换过来）。
 * ─────────────────────────────────────────────────────────────────────────────
 */

import type { UIMessage, UIMessagePart, UIDataTypes, UITools } from 'ai'

// ═══════════════════════ 领域类型（与后端共享的 schema） ═══════════════════════

/** searchSamples 工具的入参。query 是检索关键词，topK 是返回样本数（默认 3）。 */
export interface SearchSamplesInput {
  query: string
  topK?: number
}

/** 命中样本的容错原始形状：字段名容忍 camelCase / snake_case / 简写。 */
export interface SampleHitRaw {
  videoId?: string
  video_id?: string
  youtube_video_id?: string
  id?: string
  title?: string
  start?: string
  time_start?: string
  end?: string
  time_end?: string
  description?: string
  text?: string
  desc?: string
  score?: number
  similarity?: number
  distance?: number
  keywords?: string[]
}

/** 归一化后的命中样本（渲染层唯一使用的形状）。 */
export interface SampleHit {
  videoId: string
  title: string
  start: string
  end: string
  description: string
  /** 0..1 的相似度，越大越像。原始字段可能是 score / similarity / distance。 */
  score: number
  keywords?: string[]
  /** 原始数据，供「原始 JSON」折叠区展示。 */
  raw: Record<string, unknown>
}

/** searchSamples 工具的输出。ms 是检索耗时（毫秒）。 */
export interface SearchSamplesOutput {
  ms?: number
  hits: SampleHit[]
}

/** 旧版协议（《团队项目说明》§4.2）的 Part 联合类型。 */
export type LegacyPart =
  | { type: 'text'; text: string }
  | {
      type: 'tool-call'
      toolCallId: string
      toolName: string
      input: SearchSamplesInput
    }
  | {
      type: 'tool-result'
      toolCallId: string
      toolName: string
      output: { ms: number; hits: SampleHitRaw[] }
    }

// ══════════════════════════════ 视图模型 ══════════════════════════════════════

export type ToolActivityState = 'running' | 'done' | 'error'

export interface ToolActivity {
  callId: string
  toolName: string
  state: ToolActivityState
  /** 工具入参（对象，若流式还没传完则为 undefined）。 */
  input?: unknown
  /** 入参的原始 JSON 文本（流式过程中逐步增长，可用来展示“正在输入的关键词”）。 */
  inputText: string
  /** 工具出参（对象）。 */
  output?: unknown
  outputText: string
  errorText?: string
  /** 前端观察到该工具调用的时间（用于计时）。 */
  startedAt: number
  finishedAt?: number
  /** 后端报告/实际测得的耗时（毫秒），优先用后端值。 */
  ms?: number
  /** searchSamples 命中样本（已归一化）。 */
  hits?: SampleHit[]
}

export type UiPartView =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; activity: ToolActivity }
  | { kind: 'reasoning'; text: string }

/** 把一条 UIMessage 的 parts 转为渲染视图模型。 */
export function messageToViews(message: UIMessage): UiPartView[] {
  return partsToViews(message.parts ?? [])
}

// ═══════════════════════════ 归一化实现（防御式解析） ═══════════════════════════

type LoosePart = Record<string, unknown>

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 从 `tool-<toolName>` / `dynamic-tool` part 提取工具名。 */
function toolNameOf(part: LoosePart, type: string): string {
  if (typeof part.toolName === 'string' && part.toolName.length > 0) {
    return part.toolName
  }
  return type.startsWith('tool-') ? type.slice('tool-'.length) : type
}

/** AI SDK part 的 state 字段 → 我们的三态。 */
function stateOf(state: unknown): ToolActivityState {
  const s = String(state ?? '')
  if (s === 'output-available') return 'done'
  if (s === 'output-error') return 'error'
  // input-streaming / input-available / output-streaming / 其它未知状态
  return 'running'
}

function msOf(output: unknown): number | undefined {
  if (!isRecord(output)) return undefined
  const candidates = [output.ms, output.elapsed, output.durationMs, output.took, output.elapsedMs]
  for (const c of candidates) {
    if (typeof c === 'number' && Number.isFinite(c) && c >= 0) return c
    if (typeof c === 'string') {
      const n = Number(c)
      if (Number.isFinite(n) && n >= 0) return n
    }
  }
  return undefined
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/**
 * 解析命中样本：容忍 hits/results/samples/matches 以及裸数组，
 * 容忍字段名差异，并把 distance 换算成相似度。
 */
export function parseHits(output: unknown): SampleHit[] | undefined {
  let arr: unknown[] | undefined
  if (Array.isArray(output)) {
    arr = output
  } else if (isRecord(output)) {
    for (const key of ['hits', 'results', 'samples', 'matches', 'items']) {
      if (Array.isArray(output[key])) {
        arr = output[key] as unknown[]
        break
      }
    }
  }
  if (!arr) return undefined

  const hits: SampleHit[] = []
  for (const item of arr) {
    if (!isRecord(item)) continue
    const videoId = str(
      item.videoId ?? item.video_id ?? item.youtube_video_id ?? item.id,
    )
    if (!videoId && !str(item.title ?? '')) continue // 完全没信息，跳过
    let score = 0
    if (typeof item.score === 'number') score = item.score
    else if (typeof item.similarity === 'number') score = item.similarity
    else if (typeof item.distance === 'number') score = Math.max(0, 1 - item.distance)
    hits.push({
      videoId,
      title: str(item.title ?? item.name ?? ''),
      start: str(item.start ?? item.time_start ?? ''),
      end: str(item.end ?? item.time_end ?? ''),
      description: str(item.description ?? item.text ?? item.desc ?? ''),
      score: Math.min(1, Math.max(0, score)),
      keywords: Array.isArray(item.keywords)
        ? item.keywords.filter((k): k is string => typeof k === 'string')
        : undefined,
      raw: item,
    })
  }
  return hits.length > 0 ? hits : undefined
}

/**
 * 把一条消息的 parts（AI SDK 协议 或 旧版 Part 协议，可混用）
 * 归一成渲染视图模型。旧版 tool-call / tool-result 按 toolCallId 合并。
 */
export function partsToViews(
  parts: UIMessagePart<UIDataTypes, UITools>[] | LegacyPart[],
): UiPartView[] {
  const loose = parts as unknown as LoosePart[]
  const views: UiPartView[] = []

  // 第一遍：登记旧版 tool-call，用于与 tool-result 配对
  const pending = new Map<string, ToolActivity>()

  for (const part of loose) {
    const type = str(part.type)

    if (type === 'text') {
      const text = str(part.text)
      if (text.length > 0) views.push({ kind: 'text', text })
      continue
    }

    if (type === 'reasoning') {
      const text = str(part.text)
      if (text.length > 0) views.push({ kind: 'reasoning', text })
      continue
    }

    // ── 旧版协议：tool-call ──
    if (type === 'tool-call') {
      const callId = str(part.toolCallId ?? part.id ?? '')
      const name = str(part.toolName ?? '')
      const input = isRecord(part.input) ? part.input : undefined
      const activity: ToolActivity = {
        callId,
        toolName: name,
        state: 'running',
        input,
        inputText: input ? JSON.stringify(input) : '',
        output: undefined,
        outputText: '',
        startedAt: Date.now(),
      }
      if (callId) {
        pending.set(callId, activity)
      } else {
        // 没有 id 的旧 tool-call，直接当作一次已完成的工具调用展示
        activity.state = 'done'
        activity.finishedAt = activity.startedAt
        views.push({ kind: 'tool', activity })
      }
      continue
    }

    // ── 旧版协议：tool-result（与 tool-call 配对） ──
    if (type === 'tool-result') {
      const callId = str(part.toolCallId ?? part.id ?? '')
      const output = part.output
      const base = pending.get(callId)
      const activity: ToolActivity =
        base ?? {
          callId,
          toolName: str(part.toolName ?? ''),
          state: 'done',
          input: undefined,
          inputText: '',
          output,
          outputText: output ? JSON.stringify(output) : '',
          startedAt: Date.now(),
        }
      activity.output = output
      activity.outputText = output ? JSON.stringify(output) : ''
      activity.state = 'done'
      activity.finishedAt = activity.startedAt
      activity.ms = msOf(output)
      activity.hits = parseHits(output)
      pending.delete(callId)
      if (!base) views.push({ kind: 'tool', activity })
      continue
    }

    // ── AI SDK 协议：tool-<name> / dynamic-tool ──
    if (type.startsWith('tool-') || type === 'dynamic-tool') {
      const callId = str(part.toolCallId ?? part.id ?? '')
      const name = toolNameOf(part, type)
      const input = part.input
      const output = part.output
      const inputText = str(part.inputText ?? '')
      const outputText = str(part.outputText ?? '')
      const errorText = str(part.errorText ?? part.error ?? '')
      const state = stateOf(part.state)

      const activity: ToolActivity = {
        callId,
        toolName: name,
        state,
        input,
        inputText,
        output,
        outputText,
        errorText: errorText || undefined,
        startedAt: Date.now(),
      }
      if (state !== 'running') {
        activity.finishedAt = activity.startedAt
        activity.ms = msOf(output)
        activity.hits = parseHits(output)
      }
      views.push({ kind: 'tool', activity })
      continue
    }

    // ── 其它 part（source-url / file 等）：轻量降级为文本 ──
    if (type === 'source-url' || type === 'source') {
      const url = str(part.url)
      if (url) views.push({ kind: 'text', text: url })
      continue
    }
    if (type === 'file') {
      const media = str(part.mediaType ?? part.mimeType ?? '')
      const url = str(part.url ?? part.data ?? '')
      if (url) views.push({ kind: 'text', text: media ? `[文件: ${media}](${url})` : url })
    }
  }

  // 第二遍：还没有等到 tool-result 的旧版 tool-call → 保持 running 状态插入
  // （旧协议流式传输时，call 出现到 result 到达之间应该有中间态）
  if (pending.size > 0) {
    // 与已有 view 的插入顺序无关：旧协议通常是 call 在前、result 在后。
    // 这里把仍 pending 的 call 追加到末尾（它们还没有 result，属于最近发生）。
    for (const activity of pending.values()) {
      views.push({ kind: 'tool', activity })
    }
  }

  return views
}

// ═══════════════════════════ 工具（YouTube 链接等） ═══════════════════════════

/** "MM:SS" / "H:MM:SS" / 纯数字 / "12s" → 秒数。解析失败返回 0。 */
export function timeToSeconds(t: string): number {
  if (!t) return 0
  const s = t.trim()
  if (/^\d+(\.\d+)?$/.test(s)) return Math.floor(Number(s))
  const m = s.match(/^(\d+):(\d{1,2})(?::(\d{1,2}))?$/)
  if (m) {
    const h = m[3] ? Number(m[1]) : 0
    const min = m[3] ? Number(m[2]) : Number(m[1])
    const sec = m[3] ? Number(m[3]) : Number(m[2])
    return h * 3600 + min * 60 + sec
  }
  const m2 = s.match(/^(\d+(?:\.\d+)?)s$/i)
  if (m2) return Math.floor(Number(m2[1]))
  return 0
}

/**
 * 「打开原片对应时间」链接。
 * 数据里有 id 和时间戳：https://www.youtube.com/watch?v=<id>&t=<秒>
 * 非 YouTube id（或没有 id）返回 undefined。
 */
export function youtubeLink(hit: SampleHit): string | undefined {
  const id = hit.videoId?.trim()
  if (!id) return undefined
  const secs = timeToSeconds(hit.start)
  if (/^[A-Za-z0-9_-]{6,16}$/.test(id)) {
    return `https://www.youtube.com/watch?v=${id}${secs > 0 ? `&t=${secs}s` : ''}`
  }
  return undefined
}

// ═══════════════════════════ 工具展示元信息（纯 UI，可自行扩展） ═══════════════

export interface ToolMeta {
  label: string
  labelEn: string
  /** 该工具是否检索了样本库（命中列表展示 + 原片链接）。 */
  isSearch: boolean
  /** 从入参里提取展示用的检索关键词。 */
  queryOf: (input: unknown) => string
}

export const TOOL_META: Record<string, ToolMeta> = {
  searchSamples: {
    label: '检索样本库',
    labelEn: 'Search samples',
    isSearch: true,
    queryOf: (input) => (isRecord(input) ? str(input.query ?? input.keywords ?? '') : ''),
  },
  searchKnowledge: {
    label: '检索知识库',
    labelEn: 'Search knowledge',
    isSearch: true,
    queryOf: (input) => (isRecord(input) ? str(input.query ?? input.keywords ?? '') : ''),
  },
  searchCases: {
    label: '检索案例库',
    labelEn: 'Search cases',
    isSearch: true,
    queryOf: (input) => (isRecord(input) ? str(input.query ?? input.keywords ?? '') : ''),
  },
  search: {
    label: '检索',
    labelEn: 'Search',
    isSearch: true,
    queryOf: (input) => (isRecord(input) ? str(input.query ?? input.keywords ?? '') : ''),
  },
  inspiration: {
    label: '找灵感',
    labelEn: 'Find inspiration',
    isSearch: false,
    queryOf: (input) => (isRecord(input) ? str(input.idea ?? '') : ''),
  },
  review: {
    label: '剧本检查/生成',
    labelEn: 'Script check / generate',
    isSearch: false,
    queryOf: () => '',
  },
  storyboard: {
    label: '分镜建议/生成',
    labelEn: 'Storyboard',
    isSearch: false,
    queryOf: () => '',
  },
  schedule: {
    label: '拍摄计划',
    labelEn: 'Schedule',
    isSearch: false,
    queryOf: () => '',
  },
}

export function toolMeta(toolName: string): ToolMeta {
  return (
    TOOL_META[toolName] ?? {
      label: toolName,
      labelEn: toolName,
      isSearch: false,
      queryOf: (input) => (isRecord(input) ? JSON.stringify(input) : ''),
    }
  )
}

/** 工具入参的关键词（用于卡片上的关键词 chip）。 */
export function toolQuery(activity: ToolActivity): string {
  const meta = toolMeta(activity.toolName)
  if (activity.input !== undefined) return meta.queryOf(activity.input)
  // 流式中：从 inputText 的 JSON 里尝试解析 query
  const q = meta.queryOf(tryParseJson(activity.inputText))
  return q
}

export function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

export { type UIMessage, type UIMessagePart }
