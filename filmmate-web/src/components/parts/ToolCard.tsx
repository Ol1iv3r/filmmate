import { useEffect, useState } from 'react'
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Search,
  Database,
  BookOpen,
  Wrench,
  ChevronDown,
  FileJson,
} from 'lucide-react'
import type { ToolActivity } from '../../lib/contract'
import { toolMeta, toolQuery, tryParseJson } from '../../lib/contract'
import { cn, formatMs } from '../../lib/utils'
import { HitRow } from './HitRow'
import { RawJson } from './RawJson'

function iconFor(toolName: string) {
  if (toolName.toLowerCase().includes('sample')) return <Search size={14} />
  if (toolName.toLowerCase().includes('knowledge')) return <BookOpen size={14} />
  if (toolName.toLowerCase().includes('case')) return <Database size={14} />
  return <Wrench size={14} />
}

/** 检索关键词：从 input 或 inputText 流式 JSON 里尽力提取。 */
function queryWords(activity: ToolActivity): string[] {
  const q = toolQuery(activity)
  if (q) return q.split(/\s+/).filter(Boolean).slice(0, 4)
  const parsed = tryParseJson(activity.inputText) as Record<string, unknown> | undefined
  const raw = parsed?.query ?? parsed?.keywords
  if (typeof raw === 'string' && raw) return raw.split(/\s+/).filter(Boolean).slice(0, 4)
  return []
}

/** 一条工具调用卡片（Phase 4 核心）：状态、耗时、命中样本、原始 JSON。 */
export function ToolCard({
  activity,
  firstSeenAt,
  doneAtFallback,
  isLast,
}: {
  activity: ToolActivity
  firstSeenAt: number
  /** 后端没给 ms 时，前端观测到的完成时间。 */
  doneAtFallback?: number
  isLast: boolean
}) {
  const meta = toolMeta(activity.toolName)
  const [open, setOpen] = useState(true)
  const [jsonOpen, setJsonOpen] = useState(false)
  const [now, setNow] = useState(Date.now())

  const running = activity.state === 'running'
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 120)
    return () => clearInterval(t)
  }, [running])

  const elapsed = activity.ms ?? (doneAtFallback ?? activity.finishedAt ?? now) - firstSeenAt
  const query = queryWords(activity)
  const hasHits = !!activity.hits && activity.hits.length > 0

  return (
    <div
      className={cn(
        'tool-card',
        activity.state === 'running' && 'state-running',
        activity.state === 'done' && 'state-done',
        activity.state === 'error' && 'state-error',
      )}
    >
      <button className="tool-card-head" onClick={() => setOpen((o) => !o)}>
        <span className="tool-icon">{iconFor(activity.toolName)}</span>
        <span className="tool-name">{meta.label}</span>
        <code className="tool-fn">{activity.toolName}</code>

        {query.length > 0 && (
          <span className="tool-query">
            {query.map((q) => (
              <span key={q} className="kw-chip query">
                {q}
              </span>
            ))}
          </span>
        )}

        <span className="tool-status">
          {running && (
            <>
              <Loader2 size={13} className="spin" />
              <span className="status-text">检索中 · {formatMs(elapsed)}</span>
            </>
          )}
          {activity.state === 'done' && (
            <>
              <CheckCircle2 size={13} />
              <span className="status-text">完成 · {formatMs(elapsed)}</span>
            </>
          )}
          {activity.state === 'error' && (
            <>
              <XCircle size={13} />
              <span className="status-text">失败</span>
            </>
          )}
        </span>

        <ChevronDown size={14} className={cn('chev', open && 'flip')} />
      </button>

      {open && (
        <div className="tool-card-body">
          {/* 失败：红色错误 + 降级说明 */}
          {activity.state === 'error' && (
            <div className="tool-error-box">
              <XCircle size={14} />
              <div>
                <div className="tool-error-title">检索失败</div>
                <div className="tool-error-text">
                  {activity.errorText || '未知错误'}
                  {isLast && ' —— 已自动降级：改用本地镜头语言知识直接回答（不引用样本）。'}
                </div>
              </div>
            </div>
          )}

          {/* 命中样本预览 */}
          {hasHits && (
            <div className="hits-wrap">
              <div className="hits-title">
                命中 {activity.hits!.length} 个样本
                {activity.output !== undefined && (
                  <button className="link-btn json-toggle" onClick={() => setJsonOpen((o) => !o)}>
                    <FileJson size={12} />
                    {jsonOpen ? '收起原始 JSON' : '原始 JSON'}
                  </button>
                )}
              </div>
              {activity.hits!.map((hit, i) => (
                <HitRow key={`${hit.videoId}-${i}`} hit={hit} index={i} />
              ))}
            </div>
          )}

          {/* 非检索工具 / 没有 hit 可解析：只给原始 JSON */}
          {!hasHits && activity.output !== undefined && (
            <RawJson title="工具返回结果" data={activity.output} />
          )}

          {/* 输入参数折叠区（命中区展开时藏在 jsonOpen 里，避免重复） */}
          {activity.input !== undefined && !hasHits && (
            <RawJson title="调用参数" data={activity.input} />
          )}
          {jsonOpen && activity.input !== undefined && (
            <RawJson title="调用参数" data={activity.input} />
          )}
          {jsonOpen && activity.output !== undefined && (
            <RawJson title="完整输出" data={activity.output} defaultOpen />
          )}
        </div>
      )}
    </div>
  )
}
