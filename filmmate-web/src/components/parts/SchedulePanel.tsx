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

function icsEscape(value: unknown): string {
  return String(value ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n')
}

function icsFold(line: string): string {
  const encoder = new TextEncoder()
  if (encoder.encode(line).length <= 75) return line
  const chunks: string[] = []
  let current = ''
  let bytes = 0
  for (const char of line) {
    const size = encoder.encode(char).length
    if (bytes + size > 73) {
      chunks.push(current)
      current = ' ' + char
      bytes = 1 + size
    } else {
      current += char
      bytes += size
    }
  }
  if (current) chunks.push(current)
  return chunks.join('\r\n')
}

function icsStamp(): string {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
}

function icsDateTime(date: string | undefined, time: string | undefined, fallback: string): string {
  const day = (date || '').slice(0, 10) || new Date().toISOString().slice(0, 10)
  const clock = (time || fallback).slice(0, 5) || fallback
  return day.replace(/-/g, '') + 'T' + clock.replace(':', '') + '00'
}

function nextDay(date: string | undefined): string {
  const base = new Date(((date || '').slice(0, 10) || new Date().toISOString().slice(0, 10)) + 'T00:00:00')
  base.setDate(base.getDate() + 1)
  return base.toISOString().slice(0, 10)
}

/** Build a calendar file whose day descriptions contain the whole shooting plan. */
function buildIcs(payload: SchedulePayload): string {
  const days = payload.days ?? []
  const shots = payload.shots ?? []
  const crew = (payload.crew ?? []).map((c) => `${c.role ?? ''} x${c.count ?? 1}${c.note ? ' (' + c.note + ')' : ''}`).join('; ')
  const equipment = (payload.equipment ?? []).join('; ')
  const locations = (payload.locations ?? []).map((l) => l.name ?? '').filter(Boolean).join('; ')
  const risks = (payload.risks ?? []).map((r) => `${r.risk ?? ''} -> ${r.mitigation ?? ''}`).join('; ')
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Filmmate//Shooting Plan//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:Filmmate Shooting Plan',
  ]
  const stamp = icsStamp()
  days.forEach((day, index) => {
    const date = day.date
    const start = icsDateTime(date, day.call, '08:00')
    let end = icsDateTime(date, day.wrap, '19:00')
    if (end <= start) end = icsDateTime(nextDay(date), day.wrap, '19:00')
    const dayShots = shots.filter((s) => s.day === (day.day ?? index + 1))
    const shotLines = (dayShots.length ? dayShots : shots).map((s) =>
      `#${s.id ?? ''} | Scene ${s.scene ?? ''} | ${s.shot_type ?? ''} | ${s.angle ?? ''} | ${s.movement ?? ''} | ${s.duration ?? ''} | ${s.description ?? ''}`
    )
    const description = [
      `Shooting plan: ${payload.summary ?? ''}`,
      `Preferences: ${payload.preferences ?? ''}`,
      `Day: ${day.day ?? index + 1} | Date: ${date ?? ''} | Call: ${day.call ?? ''} | Wrap: ${day.wrap ?? ''}`,
      `Scenes: ${(day.scenes ?? []).join(', ')}`,
      `Notes: ${day.notes ?? ''}`,
      '',
      'Shot schedule:',
      ...shotLines,
      '',
      `Crew: ${crew}`,
      `Equipment: ${equipment}`,
      `Locations: ${locations}`,
      `Risks: ${risks}`,
    ].join('\n')
    const summary = `Day ${day.day ?? index + 1} — Filmmate shooting plan`
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:filmmate-${stamp}-day-${day.day ?? index + 1}@filmmate.local`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART:${start}`)
    lines.push(`DTEND:${end}`)
    lines.push(icsFold(`SUMMARY:${icsEscape(summary)}`))
    if (locations) lines.push(icsFold(`LOCATION:${icsEscape(locations)}`))
    lines.push(icsFold(`DESCRIPTION:${icsEscape(description)}`))
    lines.push('END:VEVENT')
  })
  if (!days.length) {
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:filmmate-${stamp}@filmmate.local`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(icsFold(`SUMMARY:${icsEscape('Filmmate shooting plan')}`))
    lines.push(icsFold(`DESCRIPTION:${icsEscape(payload.summary ?? 'Shooting plan')}`))
    lines.push('END:VEVENT')
  }
  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

/** 拍摄计划：详细方案 + 拍摄日 + shot schedule + 下载日历（.ics）。 */
export function SchedulePanel({ payload }: { payload: SchedulePayload }) {
  const { t, lang } = useI18n()
  const days = payload.days ?? []
  if (!days.length && !payload.summary) return null

  const downloadIcs = () => {
    const blob = new Blob([buildIcs(payload)], { type: 'text/calendar;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = lang === 'en' ? 'shooting-plan.ics' : '拍摄计划.ics'
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
        <button className="panel-btn" data-filmy-download onClick={downloadIcs}>{t('下载日历（.ics）', 'Download calendar (.ics)')}</button>
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
