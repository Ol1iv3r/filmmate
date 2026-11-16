interface CalendarEvent {
  title?: string
  start?: string
  end?: string
  location?: string
  description?: string
}

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

interface SchedulePayload {
  summary?: string
  crew?: { role?: string; count?: number; note?: string }[]
  equipment?: string[]
  locations?: { name?: string; note?: string }[]
  days?: DayPlan[]
  risks?: { risk?: string; mitigation?: string }[]
  calendar?: CalendarEvent[]
  shots_count?: number
  text?: string
}

function icsTime(value: string | undefined): string {
  const v = (value || '').trim()
  if (!v) return ''
  return v.replace(/[-:]/g, '').replace(/\.\d+/, '').replace(' ', 'T').slice(0, 15)
}

function icsEscape(value: string | undefined): string {
  return (value || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n')
}

function buildIcs(payload: SchedulePayload): string {
  const events: CalendarEvent[] = []
  if (Array.isArray(payload.calendar) && payload.calendar.length) {
    events.push(...payload.calendar)
  } else {
    for (const d of payload.days ?? []) {
      if (!d.date) continue
      const start = d.date + 'T' + (d.call || '09:00') + ':00'
      const end = d.date + 'T' + (d.wrap || '18:00') + ':00'
      events.push({
        title: 'Day ' + (d.day ?? '') + ' 拍摄',
        start, end, location: '',
        description: (d.scenes ?? []).join('；') + (d.notes ? '\n' + d.notes : ''),
      })
    }
  }
  const stamp = icsTime(new Date().toISOString().slice(0, 16).replace('T', 'T')) + 'Z'
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Filmmate//Shooting Plan//CN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ]
  events.forEach((ev, i) => {
    lines.push('BEGIN:VEVENT')
    lines.push('UID:filmmate-' + Date.now() + '-' + i + '@filmmate.local')
    lines.push('DTSTAMP:' + stamp)
    if (ev.start) lines.push('DTSTART:' + icsTime(ev.start) + (ev.start.length <= 10 ? '' : ''))
    if (ev.end) lines.push('DTEND:' + icsTime(ev.end))
    lines.push('SUMMARY:' + icsEscape(ev.title || '拍摄日'))
    if (ev.location) lines.push('LOCATION:' + icsEscape(ev.location))
    if (ev.description) lines.push('DESCRIPTION:' + icsEscape(ev.description))
    lines.push('END:VEVENT')
  })
  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

/** 拍摄计划：详细方案 + 拍摄日 + 下载日历（.ics）。 */
export function SchedulePanel({ payload }: { payload: SchedulePayload }) {
  const days = payload.days ?? []
  if (!days.length && !payload.summary) return null

  const downloadIcs = () => {
    const blob = new Blob([buildIcs(payload)], { type: 'text/calendar;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '拍摄计划.ics'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="schedule-panel">
      {payload.summary && <div className="logline-box"><div className="logline-title">拍摄方案</div><div className="logline-summary">{payload.summary}</div></div>}
      {(payload.crew?.length || payload.equipment?.length) ? (
        <div className="schedule-meta">
          {payload.crew?.length ? <div><b>人员</b>：{payload.crew.map((c) => (c.role || '') + '×' + (c.count ?? 1)).join('、')}</div> : null}
          {payload.equipment?.length ? <div><b>器材</b>：{payload.equipment.join('、')}</div> : null}
          {payload.locations?.length ? <div><b>场景</b>：{payload.locations.map((l) => l.name || '').join('、')}</div> : null}
        </div>
      ) : null}
      <div className="panel-head">
        <span>拍摄日（{days.length} 天 · {payload.shots_count ?? 0} 个镜头）</span>
        <button className="panel-btn" onClick={downloadIcs}>下载日历（.ics）</button>
      </div>
      <div className="table-scroll">
        <table className="sb-table">
          <thead>
            <tr><th>Day</th><th>日期</th><th>时间</th><th>场次</th><th>要点</th></tr>
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
      {payload.risks?.length ? (
        <div className="schedule-risks"><b>风险与预案</b>：{payload.risks.map((r) => (r.risk || '') + '→' + (r.mitigation || '')).join('；')}</div>
      ) : null}
    </div>
  )
}
