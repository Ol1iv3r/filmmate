import { ExternalLink } from 'lucide-react'
import type { SampleHit } from '../../lib/contract'
import { youtubeLink } from '../../lib/contract'
import { ExpandableText } from './RawJson'

/** 相似度百分比。 */
export function scorePercent(score: number): string {
  return `${Math.round(score * 100)}%`
}

/** 一条命中样本：标题、时间段、相似度、描述、原片链接。 */
export function HitRow({ hit, index }: { hit: SampleHit; index: number }) {
  const link = youtubeLink(hit)
  const pct = scorePercent(hit.score)
  return (
    <div className="hit-row">
      <div className="hit-head">
        <span className="hit-index">{String(index + 1).padStart(2, '0')}</span>
        <span className="hit-title" title={hit.title}>
          {hit.title || '（未命名样本）'}
        </span>
        {hit.start || hit.end ? (
          <span className="hit-time">
            {hit.start || '00:00'}–{hit.end || hit.start || ''}
          </span>
        ) : null}
        {link && (
          <a className="hit-link" href={link} target="_blank" rel="noreferrer noopener" title="打开原片对应时间">
            <ExternalLink size={12} />
            原片
          </a>
        )}
      </div>
      <div className="hit-score">
        <div className="hit-score-bar">
          <div className="hit-score-fill" style={{ width: pct }} />
        </div>
        <span className="hit-score-num">相似度 {pct}</span>
      </div>
      {hit.description && <ExpandableText text={hit.description} max={120} />}
      {hit.keywords && hit.keywords.length > 0 && (
        <div className="hit-keywords">
          {hit.keywords.slice(0, 6).map((k) => (
            <span key={k} className="kw-chip">
              {k}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
