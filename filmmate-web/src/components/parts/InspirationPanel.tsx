import { useState } from 'react'
import { useI18n } from '../../lib/i18n'

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
  source?: string
}

interface InspirationStyle {
  style_name?: string
  why_fits?: string
  theme?: string
}

interface InspirationPayload {
  kind?: string
  idea?: string
  films?: InspiredFilm[]
  styles?: InspirationStyle[]
}

/** 找灵感结果：每部契合电影用 2x2 四格静帧展示，点击可放大。 */
export function InspirationPanel({ payload }: { payload: InspirationPayload }) {
  const { t, lang } = useI18n()
  const films = payload.films ?? []
  const styles = payload.styles ?? []
  const [zoom, setZoom] = useState<string | null>(null)

  const useTheme = (index: number) => {
    window.dispatchEvent(new CustomEvent('filmmate:select-theme', {
      detail: { index, styleName: styles[index]?.style_name ?? '' },
    }))
  }
  if (!films.length) return null
  return (
    <div className="insp-panel">
      <div className="insp-head">
        {t('题材：', 'Genre: ')}{payload.kind ?? '—'}
        {payload.idea ? '　｜　' + t('关键词：', 'Keywords: ') + payload.idea : ''}
        　{t('（点击静帧可放大）', '(click a still to zoom)')}
      </div>
      {films.map((f, i) => (
        <div className="insp-film" key={f.id ?? i}>
          <div className="insp-film-head">
            <span className="insp-idx">{t('契合电影', 'Matching film')} {i + 1}</span>
            {f.source === 'personal' && (
              <span className="insp-ref-badge">{t('你收藏的参考片', 'Saved reference')}</span>
            )}
            {lang === 'en'
              ? `“${f.title_en ?? f.title_zh ?? ''}”`
              : `《${f.title_zh ?? ''}》`}
            {f.year ? ` (${f.year})` : ''}
            {f.duration ? '　' + f.duration : ''}
            {f.url && (
              <a className="link-btn" href={f.url} target="_blank" rel="noreferrer">
                {t('原片链接', 'Watch link')}
              </a>
            )}
            {styles[i]?.theme && (
              <button className="panel-btn" onClick={() => useTheme(i)}>
                {t('用这个主题写剧本', 'Use this theme for the script')}
              </button>
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
