/**
 * Mock 流式引擎 —— 没有后端时，用真实样本数据（50 部片、500+ 镜头段）
 * 模拟「模型先 tool call 检索样本库，再用样本生成回答」的完整过程。
 *
 * 输出的 chunk 与 Vercel AI SDK 后端完全同构（UIMessageChunk），
 * 所以前端渲染路径 = 真实后端渲染路径，只换 transport。
 */
import type { UIMessageChunk } from 'ai'
import type { MockSample, MockSegment } from './types'
import samplesRaw from './samples.json'

const SAMPLES = samplesRaw as unknown as MockSample[]

export type Intent = 'storyboard' | 'review' | 'rundown' | 'inspiration' | 'chat'

// ── 意图识别 ──────────────────────────────────────────────

export function detectIntent(text: string): Intent {
  const t = text.toLowerCase()
  const has = (pats: RegExp[]) => pats.some((p) => p.test(text) || p.test(t))
  if (has([/分镜/, /storyboard/, /shot\s*list/, /镜头/, /运镜/, /景别/, /机位/])) return 'storyboard'
  if (has([/剧本/, /漏洞/, /审稿/, /检查/, /script/, /review/, /plot/, /逻辑/])) return 'review'
  if (has([/rundown/, /通告/, /拍摄计划/, /日程/, /schedule/, /时间表/, /排期/])) return 'rundown'
  if (has([/灵感/, /idea/, /参考/, /reference/, /广告/, /commercial/, /风格/, /style/, /类似/])) return 'inspiration'
  return 'chat'
}

// ── 检索模拟（真实样本 + 关键词打分） ───────────────────

/** 中英关键词混合提取：英文单词 + 中文 2-gram。 */
function tokensOf(text: string): string[] {
  const toks: string[] = []
  const latin = text.toLowerCase().match(/[a-z][a-z0-9-]{2,}/g)
  if (latin) toks.push(...latin)
  const han = text.replace(/[^\u4e00-\u9fa5]/g, '')
  for (let i = 0; i + 1 < han.length; i++) toks.push(han.slice(i, i + 2))
  return toks
}

const INTENT_QUERY_HINTS: Record<Intent, string[]> = {
  storyboard: ['分镜 镜头语言 运镜 景别', 'commercial shot framing'],
  review: ['剧本 节奏 逻辑漏洞 情节', 'script pacing review'],
  rundown: ['拍摄 通告 流程 高效', 'production rundown'],
  inspiration: ['创意 广告 视觉 风格', 'creative commercial style'],
  chat: ['镜头语言 灯光 收音', 'cinematography'],
}

export interface MockHit {
  videoId: string
  title: string
  start: string
  end: string
  description: string
  score: number
  keywords: string[]
  segmentIndex: number
}

function segmentScore(seg: MockSegment, tokens: string[]): number {
  let s = 0
  const hay = (seg.keywords.join(' ').toLowerCase() + ' ' + seg.description.toLowerCase())
  for (const t of tokens) if (hay.includes(t)) s += 1
  return s
}

export function pickHits(userText: string, count = 4): MockHit[] {
  const tokens = [
    ...new Set([...tokensOf(userText), ...tokensOf(INTENT_QUERY_HINTS[detectIntent(userText)].join(' '))]),
  ]
  const scored: { s: MockSample; seg: MockSegment; idx: number; score: number; kw: number }[] = []
  for (const s of SAMPLES) {
    const sampleTokens = (s.keywords ?? []).join(' ').toLowerCase()
    let kw = 0
    for (const t of tokens) if (sampleTokens.includes(t)) kw += 2
    s.segments.forEach((seg, idx) => {
      const sc = segmentScore(seg, tokens)
      if (sc + kw > 0) scored.push({ s, seg, idx, score: sc, kw })
    })
  }
  scored.sort((a, b) => b.score + b.kw - (a.score + a.kw))
  const seen = new Set<string>()
  const hits: MockHit[] = []
  for (const item of scored) {
    if (seen.has(item.s.videoId)) continue
    seen.add(item.s.videoId)
    hits.push({
      videoId: item.s.videoId,
      title: item.s.title,
      start: item.seg.time_start,
      end: item.seg.time_end,
      description: item.seg.description,
      score: item.score,
      keywords: item.seg.keywords,
      segmentIndex: item.idx,
    })
    if (hits.length >= count) break
  }
  // 兜底：实在没匹配就取几部热门样本，保证演示不空
  if (hits.length === 0) {
    const shuffled = [...SAMPLES].sort(() => Math.random() - 0.5).slice(0, count)
    for (const s of shuffled) {
      hits.push({
        videoId: s.videoId,
        title: s.title,
        start: s.segments[0].time_start,
        end: s.segments[0].time_end,
        description: s.segments[0].description,
        score: 0.62,
        keywords: s.segments[0].keywords,
        segmentIndex: 0,
      })
    }
  }
  // 相似度美化：0.87 → 0.62 递减，让卡片有层次感
  hits.forEach((h, i) => {
    h.score = Math.max(0.5, 0.92 - i * 0.08 - Math.random() * 0.03)
  })
  return hits
}

// ── 回答生成（markdown，演示质量优先） ───────────────────

const SHOT_SIZE: [RegExp, string][] = [
  [/extreme\s*close|extreme\s*cu|特写|大特写/, '大特写'],
  [/close[- ]?up|close\s*shot|特写/, '特写'],
  [/medium\s*close/, '中近景'],
  [/medium\s*shot|中景/, '中景'],
  [/wide\s*shot|long\s*shot|全景|远景/, '全景'],
  [/establishing/, '定场全景'],
  [/pov/, '主观视角'],
]
const CAMERA: [RegExp, string][] = [
  [/high[- ]?angle|俯/, '俯拍'],
  [/low[- ]?angle|仰/, '仰拍'],
  [/over[- ]?the[- ]?shoulder|肩拍/, '过肩'],
  [/eye[- ]?level/, '平视'],
  [/aerial|drone|航拍/, '航拍'],
]
const MOVEMENT: [RegExp, string][] = [
  [/tracking|dolly|跟拍/, '跟拍'],
  [/pan|摇摄|横摇/, '横摇'],
  [/tilt/, '纵摇'],
  [/zoom|push[- ]?in|推/, '推近'],
  [/static|fixed|locked|固定/, '固定'],
  [/handheld|手持/, '手持'],
  [/slow\s*motion|慢动作/, '慢动作'],
]

function matchFirst(desc: string, table: [RegExp, string][]): string {
  const d = desc.toLowerCase()
  for (const [re, label] of table) if (re.test(d)) return label
  return ''
}

function shotOf(seg: MockSegment): { size: string; camera: string; movement: string } {
  return {
    size: matchFirst(seg.description, SHOT_SIZE),
    camera: matchFirst(seg.description, CAMERA),
    movement: matchFirst(seg.description, MOVEMENT),
  }
}

function storyboardAnswer(hits: MockHit[], userText: string): string {
  const rows = hits.slice(0, 4).map((h, i) => {
    const seg = SAMPLES.find((s) => s.videoId === h.videoId)?.segments[h.segmentIndex]
    const shot = seg ? shotOf(seg) : { size: '中景', camera: '平视', movement: '固定' }
    return `| ${i + 1} | ${shot.size || '中景'} | ${shot.camera || '平视'} | ${shot.movement || '固定'} | ${h.end}-${h.start} 节奏参考 | ${h.description.slice(0, 60).replace(/\|/g, '／')}… |`
  })
  return [
    `根据你的想法，我检索到了 ${hits.length} 个最接近的参考片段。下面这版分镜直接借鉴了它们的**景别、机位和运镜节奏**：`,
    '',
    '| 镜号 | 景别 | 机位 | 运镜 | 时长参考 | 画面 |',
    '| --- | --- | --- | --- | --- | --- |',
    ...rows,
    '',
    '> 💡 第 1 镜用「定场 + 建立节奏」开头（参考《' + (hits[0]?.title ?? '') + `》${hits[0] ? hits[0].start : ''}），第 2 镜起跟着主体运动走跟拍，结尾收在一个特写上会更有记忆点。`,
    '',
    `需要的话我可以：① 按你的剧本逐镜细化 ② 换成你指定的风格（如 Prada 式冷调）③ 导出成拍摄通告单。`,
  ].join('\n')
}

function reviewAnswer(userText: string): string {
  const hasNightDay = /夜/.test(userText) && /日|白天|早/.test(userText)
  const lines: string[] = [
    '我按「时间线 → 人物去向 → 伏笔回收 → 对白信息量」四层把剧本过了一遍：',
    '',
    '| 问题 | 严重度 | 位置 | 建议 |',
    '| --- | --- | --- | --- |',
  ]
  if (hasNightDay) {
    lines.push('| 时间跳变：夜戏与日戏之间缺少过渡镜头或时间标注 | 🔴 高 | 第 1–2 场之间 | 加一场「次日清晨」定场镜，或在对白里点明时间跨度 |')
  }
  lines.push('| 人物信息密度偏低：对白以闲聊开场，前 15 秒没有建立冲突 | 🟡 中 | 开场 | 把最关键的矛盾提前到第 3 句对白内 |')
  lines.push('| 伏笔未闭环：结尾没有回应开场的悬念 | 🟡 中 | 结尾 | 给一个 3 秒的回扣镜头（道具或对白）形成闭环 |')
  lines.push('', '**总体评分：7.5 / 10** — 结构完整、对白口语化好；主要扣分在节奏和信息密度。', '')
  lines.push('> 以上是演示版规则引擎的结果；接入 LLM 后会把样本库检索 + 深度语义审查合并（在线模式）。')
  return lines.join('\n')
}

function rundownAnswer(hits: MockHit[]): string {
  return [
    '参考了样本库里「高效小团队拍摄」的节奏，给你排了一版 2 小时的通告单（6 人小团队、单机）：',
    '',
    '| 时间 | 环节 | 内容 | 备注 |',
    '| --- | --- | --- | --- |',
    '| 09:00–09:15 | 集合 | 设备领取、安全简报 | 提前一晚充好电池 |',
    '| 09:15–09:45 | 定场镜头 | 参照《' + (hits[0]?.title ?? 'Duck Run') + '》' + (hits[0] ? ` ${hits[0].start}–${hits[0].end}` : '') + ' 的定场拍法 | 顺光，一次过 |',
    '| 09:45–10:30 | 主戏 A | 正反打对话（每镜 2–3 条） | 同期声，注意底噪 |',
    '| 10:30–10:40 | 转场 | 换镜头 / 换机位 | 提前走位 |',
    '| 10:40–10:55 | 主戏 B | 跟拍运动镜头（参考 ' + (hits[1]?.title ?? '样本') + '） | 稳定器 |',
    '| 10:55–11:00 | 收尾 | 空镜 + 特写补拍 | 留给剪辑转场用 |',
    '',
    '> ⏱ 每镜平均 3–5 分钟，留 15% 缓冲；空镜和特写最后拍，主戏一定优先保。',
  ].join('\n')
}

function inspirationAnswer(hits: MockHit[]): string {
  const cards = hits.slice(0, 3).map((h) => `- **《${h.title}》**（${h.start}–${h.end}）：${h.description.slice(0, 80).replace(/\|/g, '／')}…`)
  return [
    `你的想法很适合往这几个方向发散 —— 我从样本库里挑了 ${hits.length} 个真实广告/短片的镜头段作参考：`,
    '',
    ...cards,
    '',
    '**给你的三个落地建议**：',
    '',
    '1. **开场 3 秒**：参考《' + (hits[0]?.title ?? '') + '》用反差制造好奇（不解释，先展示）；',
    '2. **中段节奏**：每 5–8 秒换一次机位/景别，避免观众疲劳；',
    '3. **结尾钩子**：留一个 2 秒的意外反转，让人想再看一遍。',
    '',
    '要不要我基于其中一部出完整分镜？',
  ].join('\n')
}

function chatAnswer(): string {
  return [
    '我是 Filmmate，影视创作领域的 AI 助理。我可以帮你：',
    '',
    '- 🔍 **检查剧本漏洞**（时间线 / 人物 / 伏笔）',
    '- 🎞️ **出分镜**：先检索相似的真实影片样本，再给你带景别/机位/运镜的分镜表',
    '- 📋 **排拍摄 Rundown** 与 🗓️ **拍摄日程**',
    '- 💡 **找灵感**：一句话描述想法，我检索样本库给你参考片段',
    '',
    '比如直接发我：「给一个 30 秒可爱宠物广告出分镜」。',
  ].join('\n')
}

export interface AnswerPlan {
  intent: Intent
  intro: string
  hits?: MockHit[]
  answer: string
  query: string
  topK: number
  /** 模拟检索耗时（后端报告的 ms）。 */
  searchMs: number
  /** 是否模拟一次工具错误（用于演示降级 UI）。 */
  simulateError: boolean
}

export function buildPlan(userText: string): AnswerPlan {
  const intent = detectIntent(userText)
  const simulateError = /错误演示|\[error\]|simulate\s*error/i.test(userText)
  const hints = INTENT_QUERY_HINTS[intent]
  const query = `${hints[0].slice(0, 12)} ${userText.replace(/\s+/g, ' ').slice(0, 24)}`.trim()
  const topK = 4
  const searchMs = 700 + Math.floor(Math.random() * 700)

  const intros: Record<Intent, string> = {
    storyboard: '好的，先到样本库里找和你想法最接近的参考片，再给分镜。',
    review: '明白。我会先用检查清单过一遍结构，再检索类似风格的样本对照节奏。',
    rundown: '好，我按样本库里的拍摄节奏给你排通告单。',
    inspiration: '我来检索样本库里最接近你描述的真实片段。',
    chat: '',
  }

  if (intent === 'chat') {
    return { intent, intro: '', answer: chatAnswer(), query: '', topK: 0, searchMs, simulateError }
  }

  const hits = pickHits(userText, topK)
  const answer =
    intent === 'storyboard'
      ? storyboardAnswer(hits, userText)
      : intent === 'review'
        ? reviewAnswer(userText)
        : intent === 'rundown'
          ? rundownAnswer(hits)
          : inspirationAnswer(hits)

  return { intent, intro: intros[intent], hits, answer, query, topK, searchMs, simulateError }
}

// ── chunk 流构建 ─────────────────────────────────────────

export interface MockStreamStep {
  /** 该步开始前等待多久（毫秒）。 */
  delay: number
  chunks: UIMessageChunk[]
}

/** 把一段文本切成自然的流式小段。 */
function textChunks(text: string): string[] {
  const out: string[] = []
  let i = 0
  while (i < text.length) {
    const n = 2 + Math.floor(Math.random() * 5)
    out.push(text.slice(i, i + n))
    i += n
  }
  return out
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/**
 * 生成一条 assistant 消息的完整 chunk 计划（含 intro 文本、
 * searchSamples 工具调用的 input→output 生命周期、最终回答）。
 * review 意图会产生两个工具调用，用来演示时间线。
 */
export function buildSteps(plan: AnswerPlan): MockStreamStep[] {
  const steps: MockStreamStep[] = []
  const msgId = `msg-${Math.random().toString(36).slice(2, 10)}`

  steps.push({ delay: 300, chunks: [{ type: 'start', messageId: msgId }] })

  if (plan.intent === 'chat') {
    const t = textChunks(plan.answer)
    steps.push({ delay: 200, chunks: [{ type: 'text-start', id: 't0' }, ...t.map((d) => ({ type: 'text-delta' as const, id: 't0', delta: d }))] })
  } else if (plan.simulateError) {
    // 工具调用失败演示：检索超时 → 红色错误态 + 降级说明
    const intro = textChunks('我先试着检索样本库……')
    const tc = `tc-${Math.random().toString(36).slice(2, 8)}`
    steps.push({ delay: 200, chunks: [{ type: 'text-start', id: 't0' }, ...intro.map((d) => ({ type: 'text-delta' as const, id: 't0', delta: d }))] })
    steps.push({
      delay: 150,
      chunks: [
        { type: 'tool-input-start', toolCallId: tc, toolName: 'searchSamples', inputEncoding: 'json' },
        { type: 'tool-input-delta', toolCallId: tc, inputTextDelta: JSON.stringify({ query: plan.query }).slice(0, 12) },
        { type: 'tool-input-available', toolCallId: tc, toolName: 'searchSamples', input: { query: plan.query, topK: plan.topK } },
      ],
    })
    steps.push({
      delay: 1100,
      chunks: [{ type: 'tool-output-error', toolCallId: tc, errorText: 'sample index connection timed out (mock)' }],
    })
    const degrade = textChunks('样本库连接超时了（这是演示的降级路径）。我先用本地镜头语言知识直接给你建议：' + ' ' + plan.answer.slice(0, 120))
    steps.push({ delay: 250, chunks: [{ type: 'text-start', id: 't1' }, ...degrade.map((d) => ({ type: 'text-delta' as const, id: 't1', delta: d }))] })
  } else {
    const intro = textChunks(plan.intro)
    steps.push({ delay: 250, chunks: [{ type: 'text-start', id: 't0' }, ...intro.map((d) => ({ type: 'text-delta' as const, id: 't0', delta: d }))] })

    if (plan.intent === 'review') {
      const tc1 = `tc-${Math.random().toString(36).slice(2, 8)}`
      const knowInput = { query: '剧本检查 结构 节奏 逻辑', topK: 2 }
      steps.push({
        delay: 200,
        chunks: [
          { type: 'tool-input-start', toolCallId: tc1, toolName: 'searchKnowledge', inputEncoding: 'json' },
          { type: 'tool-input-delta', toolCallId: tc1, inputTextDelta: JSON.stringify(knowInput).slice(0, 8) },
          { type: 'tool-input-available', toolCallId: tc1, toolName: 'searchKnowledge', input: knowInput },
        ],
      })
      steps.push({
        delay: 600,
        chunks: [
          {
            type: 'tool-output-available',
            toolCallId: tc1,
            output: {
              ms: 430 + Math.floor(Math.random() * 300),
              hits: [
                { title: '剧本检查清单 · 时间线', description: '检查场与场之间的时间跳变、日夜切换是否可理解。', score: 0.91 },
                { title: '剧本检查清单 · 伏笔回收', description: '开场埋下的悬念在结尾必须有回扣镜头或对白。', score: 0.84 },
              ],
            },
          },
        ],
      })
    }

    // searchSamples 工具调用（所有非 chat 意图）
    const tc = `tc-${Math.random().toString(36).slice(2, 8)}`
    const input = { query: plan.query, topK: plan.topK }
    const inputJson = JSON.stringify(input)
    steps.push({
      delay: 180,
      chunks: [
        { type: 'tool-input-start', toolCallId: tc, toolName: 'searchSamples', inputEncoding: 'json' },
        { type: 'tool-input-delta', toolCallId: tc, inputTextDelta: inputJson.slice(0, Math.floor(inputJson.length / 2)) },
        { type: 'tool-input-delta', toolCallId: tc, inputTextDelta: inputJson.slice(Math.floor(inputJson.length / 2)) },
        { type: 'tool-input-available', toolCallId: tc, toolName: 'searchSamples', input },
      ],
    })
    steps.push({
      delay: plan.searchMs,
      chunks: [
        {
          type: 'tool-output-available',
          toolCallId: tc,
          output: {
            ms: plan.searchMs,
            hits: (plan.hits ?? []).map((h) => ({
              videoId: h.videoId,
              title: h.title,
              start: h.start,
              end: h.end,
              description: h.description,
              score: Number(h.score.toFixed(3)),
              keywords: h.keywords,
            })),
          },
        },
      ],
    })

    const answerChunks = textChunks(plan.answer)
    steps.push({
      delay: 300,
      chunks: [
        { type: 'text-start', id: 't1' },
        ...answerChunks.map((d) => ({ type: 'text-delta' as const, id: 't1', delta: d })),
        { type: 'text-end', id: 't1' },
      ],
    })
  }

  steps.push({ delay: 60, chunks: [{ type: 'finish', finishReason: 'stop' }] })
  return steps
}

/** 把步骤计划转成可中止的 ReadableStream（与后端 SSE 解码后的流同构）。 */
export function streamFromSteps(steps: MockStreamStep[], signal?: AbortSignal): ReadableStream<UIMessageChunk> {
  let cancelled = false
  const onAbort = () => {
    cancelled = true
  }
  signal?.addEventListener('abort', onAbort, { once: true })

  return new ReadableStream<UIMessageChunk>({
    async start(controller) {
      try {
        for (const step of steps) {
          if (cancelled || signal?.aborted) {
            try {
              controller.enqueue({ type: 'abort', reason: 'user-stop' })
            } catch {
              /* stream 已关闭 */
            }
            controller.close()
            signal?.removeEventListener('abort', onAbort)
            return
          }
          if (step.delay > 0) await sleep(step.delay)
          for (const chunk of step.chunks) controller.enqueue(chunk)
        }
        controller.close()
      } finally {
        signal?.removeEventListener('abort', onAbort)
      }
    },
    cancel() {
      cancelled = true
    },
  })
}
