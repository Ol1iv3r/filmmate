import { useI18n } from '../../lib/i18n'

interface Logline {
  title?: string
  title_en?: string
  theme?: string
  summary?: string
}

interface Shot {
  id?: number
  scene?: string
  shot_type?: string
  angle?: string
  movement?: string
  lens?: string
  duration?: string
  description?: string
  dialogue?: string
  lighting?: string
  sound?: string
  purpose?: string
  transition?: string
}

interface StoryboardPayload {
  logline?: Logline | null
  shots?: Shot[]
  theme?: string
  mode?: string
}

function csvCell(value: unknown) {
  return '"' + String(value ?? '').replace(/"/g, '""') + '"'
}

/** 分镜结果：梗要 + 可滚动分镜表 + 下载 CSV。 */
export function StoryboardPanel({ payload }: { payload: StoryboardPayload }) {
  const { t } = useI18n()
  const shots = payload.shots ?? []
  const logline = payload.logline

  const downloadCsv = () => {
    const headers = ['镜号', '场次', '景别', '机位', '运镜', '焦段', '时长', '画面', '台词', '光线', '声音', '目的', '转场']
    const rows = shots.map((s, i) => [
      s.id ?? i + 1, s.scene, s.shot_type, s.angle, s.movement, s.lens, s.duration,
      s.description, s.dialogue, s.lighting, s.sound, s.purpose, s.transition,
    ])
    const csv = [headers.map(csvCell).join(','), ...rows.map((r) => r.map(csvCell).join(','))].join('\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '分镜表.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  if (!shots.length) return null
  return (
    <div className="storyboard-panel">
      {logline && (
        <div className="logline-box">
          <div className="logline-title">
            {t('梗要', 'Logline')}　《{logline.title ?? '未命名'}》
            {logline.title_en ? '（' + logline.title_en + '）' : ''}
          </div>
          {logline.theme && <div className="logline-theme">{t('主题：', 'Theme: ')}{logline.theme}</div>}
          {logline.summary && <div className="logline-summary">{logline.summary}</div>}
        </div>
      )}
      <div className="panel-head">
        <span>{t('分镜表', 'Storyboard')}{'（'}{shots.length}{t(' 个镜头）', ' shots)')}</span>
        <button className="panel-btn" data-filmy-download onClick={downloadCsv}>{t('下载 CSV', 'Download CSV')}</button>
      </div>
      <div className="table-scroll">
        <table className="sb-table">
          <thead>
            <tr>
              <th>#</th><th>{t('场次', 'Scene')}</th><th>{t('景别', 'Shot')}</th><th>{t('机位', 'Angle')}</th><th>{t('运镜', 'Move')}</th><th>{t('时长', 'Dur')}</th><th>{t('画面', 'Frame')}</th><th>{t('声音', 'Sound')}</th>
            </tr>
          </thead>
          <tbody>
            {shots.map((s, i) => (
              <tr key={s.id ?? i}>
                <td>{s.id ?? i + 1}</td>
                <td>{s.scene}</td>
                <td>{s.shot_type}</td>
                <td>{s.angle}</td>
                <td>{s.movement}</td>
                <td>{s.duration}</td>
                <td>{s.description}</td>
                <td>{s.sound}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
