# Filmmate 前后端消息契约（v1 · 2026-11-12）

> 给 Jacky：这份文件定义前端（Oliver，本仓库）与后端（Jacky，Phase 2/3）之间**唯一的接口约定**。
> 实现来源：Vercel AI SDK 的 `UIMessage` / `UIMessageChunk` 流协议 + 《团队项目说明》§4.2 的 Part 结构。
> 前端实现：`src/lib/contract.ts`（类型 + 归一化）；只要满足本文件，前端零改动。

---

## 1. 聊天接口（AI SDK 标准流）

**`POST /api/chat`**

- 请求体：`{ "id": string, "messages": UIMessage[] }`（`DefaultChatTransport` 标准格式）
- 响应体：**AI SDK v5 UIMessageStream**（`streamText().toUIMessageStreamResponse()` 的输出）
- 前端用官方 `DefaultChatTransport` 消费，**不要自定义协议**。

一个标准的 OpenAI 兼容后端这样出（伪代码）：

```ts
app.post('/api/chat', async (req) => {
  const { messages } = await req.json()
  const result = streamText({
    model,
    system: SYSTEM_PROMPT,
    messages: messages.map(m => ({ role: m.role, content: m.parts
      .filter(p => p.type === 'text').map(p => p.text).join('\n') })),
    tools: { searchSamples: tool({...}) },
  })
  return result.toUIMessageStreamResponse()
})
```

要点：
1. **UIMessage 是可 JSON 序列化的纯数据** —— 与「LangChain message → dict → JSON 落盘」完全互通：
   `{ id, role, parts, createdAt? }`，parts 是 `{type:'text',text}` / `{type:'tool-<name>',toolCallId,...}` / `{type:'reasoning',text}` 的数组。
2. 流式 chunk 顺序：`start` → `text-start/text-delta/text-end` → `tool-input-start/tool-input-delta/tool-input-available` → `tool-output-available | tool-output-error` → `finish`。
3. 前端容忍字段名差异（见 §5），但**新代码请按本文件写**，不要依赖容错。

---

## 2. `searchSamples` 工具（核心，Phase 4 展示对象）

### 入参（input）

```ts
{ query: string; topK?: number }   // topK 默认 3，前端卡片只展示 query
```

### 出参（output）

```ts
{
  ms: number,                        // 检索耗时（毫秒，卡片上显示「完成 · 812ms」）
  hits: Array<{
    videoId: string,                 // YouTube id（前端拼「打开原片」链接）
    title: string,
    start: string,                   // "00:12" 或 "0:12" 或秒数
    end: string,
    description: string,             // 片段描述（请先清洗 [[00:01](url)] 标记）
    score: number,                   // 0..1 相似度
    keywords?: string[]
  }>
}
```

### 失败

`tool-output-error`，`errorText` 写清原因（如 “vector store unavailable”）。
前端会渲染红色卡片 + 「已自动降级」说明。**失败时请继续输出文本回答**（降级回答），不要中断流。

### 其它工具

`searchKnowledge` / `searchCases` 的 output 用同样形状（`hits` 里可以没有 `videoId`，
此时前端不显示「打开原片」链接）。任意其它工具名也能渲染（通用卡片 + 原始 JSON）。

---

## 3. 会话历史接口（Phase 3，可选）

启用方式：前端 `.env` 里 `VITE_REMOTE_CONVERSATIONS=1`。未启用时前端用 localStorage，互不影响。

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/api/conversations` | – | `ConversationMeta[]` |
| GET | `/api/conversations/:id` | – | `{ messages: UIMessage[] }`（404 = 不存在） |
| PUT | `/api/conversations/:id` | `{ messages: UIMessage[], title? }` | `ConversationMeta` |
| PATCH | `/api/conversations/:id` | `{ title }` | 200 |
| DELETE | `/api/conversations/:id` | – | 200 |

```ts
type ConversationMeta = { id: string; title: string; createdAt: number; updatedAt: number }
```

实现建议：`UIMessage[]` 直接 `JSON.stringify` 落盘（这就是“LangChain message → dict → JSON”），读回时 `JSON.parse`。

---

## 4. 旧版 Part 结构（兼容层，新代码不必用）

《团队项目说明》§4.2 的形状，前端 `partsToViews()` 仍支持，`toolCallId` 相同的
`tool-call` + `tool-result` 会自动合并成一张卡片：

```ts
type Part =
  | { type: 'text'; text: string }
  | { type: 'tool-call';  toolCallId: string; toolName: 'searchSamples'; input: { query: string; topK?: number } }
  | { type: 'tool-result'; toolCallId: string; toolName: 'searchSamples';
      output: { ms: number; hits: { videoId: string; title: string; start: string; end: string;
                                    description: string; score: number }[] } }
```

---

## 5. 容错清单（前端已实现，仅供了解）

- 命中容器：`hits` / `results` / `samples` / `matches` / 裸数组
- id 字段：`videoId` / `video_id` / `youtube_video_id` / `id`
- 时间字段：`start`/`time_start`、`end`/`time_end`；"MM:SS"、"H:MM:SS"、秒数、`"12s"` 都能解析
- 相似度：`score` / `similarity` / `distance`（distance 自动按 `1-d` 换算）
- 耗时：`ms` / `elapsed` / `durationMs` / `took`
- 描述：`description` / `text` / `desc`
- 工具 part：`tool-<name>`、`dynamic-tool`、旧版 `tool-call`/`tool-result` 混用都行

---

## 6. 变更记录

- v1（11-12）：初版。聊天 = AI SDK 流；`searchSamples` schema 定死；会话 REST 约定。
