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
            梗要　《{logline.title ?? '未命名'}》
            {logline.title_en ? '（' + logline.title_en + '）' : ''}
          </div>
          {logline.theme && <div className="logline-theme">主题：{logline.theme}</div>}
          {logline.summary && <div className="logline-summary">{logline.summary}</div>}
        </div>
      )}
      <div className="panel-head">
        <span>分镜表（{shots.length} 个镜头）</span>
        <button className="panel-btn" onClick={downloadCsv}>下载 CSV</button>
      </div>
      <div className="table-scroll">
        <table className="sb-table">
          <thead>
            <tr>
              <th>#</th><th>场次</th><th>景别</th><th>机位</th><th>运镜</th><th>时长</th><th>画面</th><th>声音</th>
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
