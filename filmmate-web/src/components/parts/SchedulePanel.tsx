import { useI18n } from '../../lib/i18n'

interface DayBlock {
  start?: string
  end?: string
  activity?: string
  location?: string
}

interface DayPlan {
  day?: number
  date?: string
  call?: string
  wrap?: string
  scenes?: string[]
  notes?: string
  blocks?: DayBlock[]
}

interface ShotScheduleRow {
  id?: number
  day?: number
  scene?: string
  shot_type?: string
  angle?: string
  movement?: string
  duration?: string
  description?: string
}

interface SchedulePayload {
  summary?: string
  crew?: { role?: string; count?: number; note?: string }[]
  equipment?: string[]
  locations?: { name?: string; note?: string }[]
  days?: DayPlan[]
  risks?: { risk?: string; mitigation?: string }[]
  shots_count?: number
  shots?: ShotScheduleRow[]
  preferences?: string
  text?: string
}

function csvCell(value: unknown): string {
  return '"' + String(value ?? '').replace(/"/g, '""') + '"'
}

/** Download the shooting plan as CSV (no .ics). */
function buildPlanCsv(payload: SchedulePayload, lang: 'zh' | 'en'): string {
  const en = lang === 'en'
  const rows: unknown[][] = []
  const days = payload.days ?? []
  const dayDate = new Map<number, string>()
  for (const d of days) if (d.day != null && d.date) dayDate.set(d.day, d.date)
  rows.push([en ? 'Filmmate shooting plan' : 'Filmmate 拍摄计划', payload.summary ?? ''])
  rows.push([en ? 'Preferences' : '偏好', payload.preferences ?? ''])
  rows.push([])
  rows.push([en ? 'Day' : '天', en ? 'Date' : '日期', en ? 'Call' : '集合', en ? 'Wrap' : '收工', en ? 'Scenes' : '场次', en ? 'Notes' : '要点'])
  for (const d of days) {
    rows.push([d.day ?? '', d.date ?? '', d.call ?? '', d.wrap ?? '', (d.scenes ?? []).join('; '), d.notes ?? ''])
  }
  rows.push([])
  if (payload.shots?.length) {
    rows.push([en ? 'Shot' : '镜号', en ? 'Day' : '天', en ? 'Date' : '日期', en ? 'Scene' : '场次', en ? 'Size' : '景别', en ? 'Angle' : '机位', en ? 'Movement' : '运镜', en ? 'Duration' : '时长', en ? 'Frame' : '画面'])
    for (const shot of payload.shots) {
      rows.push([shot.id ?? '', shot.day ?? '', shot.day != null ? (dayDate.get(shot.day) ?? '') : '', shot.scene ?? '', shot.shot_type ?? '', shot.angle ?? '', shot.movement ?? '', shot.duration ?? '', shot.description ?? ''])
    }
    rows.push([])
  }
  if (payload.crew?.length) {
    rows.push([en ? 'Crew' : '人员', en ? 'Role' : '职位', en ? 'Count' : '人数', en ? 'Note' : '备注'])
    for (const c of payload.crew) rows.push(['', c.role ?? '', c.count ?? 1, c.note ?? ''])
    rows.push([])
  }
  if (payload.equipment?.length) {
    rows.push([en ? 'Equipment' : '器材', payload.equipment.join('; ')])
    rows.push([])
  }
  if (payload.locations?.length) {
    rows.push([en ? 'Locations' : '场景', en ? 'Name' : '名称', en ? 'Note' : '备注'])
    for (const l of payload.locations) rows.push(['', l.name ?? '', l.note ?? ''])
    rows.push([])
  }
  if (payload.risks?.length) {
    rows.push([en ? 'Risks' : '风险', en ? 'Risk' : '风险', en ? 'Mitigation' : '预案'])
    for (const r of payload.risks) rows.push(['', r.risk ?? '', r.mitigation ?? ''])
  }
  return rows.map((row) => row.map(csvCell).join(',')).join('\r\n')
}

/** 拍摄计划：详细方案 + 拍摄日 + shot schedule + 下载 CSV。 */
export function SchedulePanel({ payload }: { payload: SchedulePayload }) {
  const { t, lang } = useI18n()
  const days = payload.days ?? []
  if (!days.length && !payload.summary) return null

  const downloadCsv = () => {
    const blob = new Blob(['\ufeff' + buildPlanCsv(payload, lang)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = lang === 'en' ? 'shooting-plan.csv' : '拍摄计划.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="schedule-panel">
      {payload.preferences && <div className="schedule-pref">{t('已按你的偏好安排：', 'Scheduled by your preferences: ')}{payload.preferences}</div>}
      {payload.summary && <div className="logline-box"><div className="logline-title">{t('拍摄方案', 'Shooting plan')}</div><div className="logline-summary">{payload.summary}</div></div>}
      {(payload.crew?.length || payload.equipment?.length) ? (
        <div className="schedule-meta">
          {payload.crew?.length ? <div><b>{t('人员', 'Crew')}</b>：{payload.crew.map((c) => (c.role || '') + '×' + (c.count ?? 1)).join(t('、', ', '))}</div> : null}
          {payload.equipment?.length ? <div><b>{t('器材', 'Gear')}</b>：{payload.equipment.join(t('、', ', '))}</div> : null}
          {payload.locations?.length ? <div><b>{t('场景', 'Locations')}</b>：{payload.locations.map((l) => l.name || '').join(t('、', ', '))}</div> : null}
        </div>
      ) : null}
      <div className="panel-head">
        <span>{t('拍摄日', 'Shoot days')}（{days.length} {t('天', 'days')} · {payload.shots_count ?? 0} {t('个镜头', 'shots')}）</span>
        <button className="panel-btn" data-filmy-download onClick={downloadCsv}>{t('下载 CSV', 'Download CSV')}</button>
      </div>
      <div className="table-scroll">
        <table className="sb-table">
          <thead>
            <tr><th>Day</th><th>{t('日期', 'Date')}</th><th>{t('时间', 'Time')}</th><th>{t('场次', 'Scenes')}</th><th>{t('要点', 'Notes')}</th></tr>
          </thead>
          <tbody>
            {days.map((d, i) => (
              <tr key={i}>
                <td>{d.day ?? i + 1}</td>
                <td>{d.date}</td>
                <td>{(d.call || '') + '-' + (d.wrap || '')}</td>
                <td>{(d.scenes ?? []).join('、')}</td>
                <td>{d.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {payload.shots?.length ? (
        <div className="shot-schedule">
          <div className="panel-head">
            <span>{t('镜头排期', 'Shot schedule')}（{payload.shots.length} {t('个镜头', 'shots')}）</span>
          </div>
          <div className="table-scroll">
            <table className="sb-table">
              <thead>
                <tr><th>#</th><th>Day</th><th>{t('场次', 'Scene')}</th><th>{t('景别', 'Size')}</th><th>{t('画面', 'Frame')}</th></tr>
              </thead>
              <tbody>
                {payload.shots.map((shot, i) => (
                  <tr key={shot.id ?? i}>
                    <td>{shot.id ?? i + 1}</td>
                    <td>{shot.day ?? '—'}</td>
                    <td>{shot.scene}</td>
                    <td>{shot.shot_type}</td>
                    <td>{shot.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      {payload.risks?.length ? (
        <div className="schedule-risks"><b>{t('风险与预案', 'Risks')}</b>：{payload.risks.map((r) => (r.risk || '') + '→' + (r.mitigation || '')).join(t('；', '; '))}</div>
      ) : null}
    </div>
  )
}
