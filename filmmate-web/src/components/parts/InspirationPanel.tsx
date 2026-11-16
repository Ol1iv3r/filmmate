import { useState } from 'react'

interface InspiredFilm {
  id?: string
  kind?: string
  title_zh?: string
  title_en?: string
  year?: number
  duration?: string
  url?: string
  platform?: string
  frames?: string[]
}

interface InspirationPayload {
  kind?: string
  idea?: string
  films?: InspiredFilm[]
  styles?: unknown[]
}

/** 找灵感结果：每部契合电影用 2x2 四格静帧展示，点击可放大。 */
export function InspirationPanel({ payload }: { payload: InspirationPayload }) {
  const films = payload.films ?? []
  const [zoom, setZoom] = useState<string | null>(null)
  if (!films.length) return null
  return (
    <div className="insp-panel">
      <div className="insp-head">
        题材：{payload.kind ?? '—'}
        {payload.idea ? '　｜　关键词：' + payload.idea : ''}
        　（点击静帧可放大）
      </div>
      {films.map((f, i) => (
        <div className="insp-film" key={f.id ?? i}>
          <div className="insp-film-head">
            <span className="insp-idx">契合电影 {i + 1}</span>
            《{f.title_zh ?? ''}》{f.year ?? ''}
            {f.duration ? '　' + f.duration : ''}
            {f.url && (
              <a className="link-btn" href={f.url} target="_blank" rel="noreferrer">
                原片链接
              </a>
            )}
          </div>
          <div className="insp-grid">
            {(f.frames ?? []).slice(0, 4).map((src, j) => (
              <img key={j} src={src} alt="still" loading="lazy" onClick={() => setZoom(src)} />
            ))}
          </div>
        </div>
      ))}
      {zoom && (
        <div className="lightbox" onClick={() => setZoom(null)}>
          <img src={zoom} alt="still-large" />
        </div>
      )}
    </div>
  )
}
