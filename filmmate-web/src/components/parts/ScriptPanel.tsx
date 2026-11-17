import { useState } from 'react'
import { API_BASE } from '../../lib/transport'
import { useI18n } from '../../lib/i18n'

interface Logline {
  title?: string
  title_en?: string
  theme?: string
  summary?: string
}

interface ScriptPayload {
  kind?: string
  logline?: Logline | null
  script_text?: string
  findings?: unknown[]
  mode?: string
}

/** 剧本结果：梗要 + 可滚动标准格式剧本 + 下载 PDF。 */
export function ScriptPanel({ payload }: { payload: ScriptPayload }) {
  const { t, lang } = useI18n()
  const [busy, setBusy] = useState(false)
  const logline = payload.logline
  const script = payload.script_text ?? ''
  if (!script) return null

  const downloadPdf = async () => {
    setBusy(true)
    try {
      const res = await fetch((API_BASE ?? '') + '/api/script/pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: logline?.title ?? (lang === 'en' ? 'Screenplay' : '剧本'), text: script }),
      })
      if (!res.ok) throw new Error(t('PDF 生成失败', 'PDF generation failed'))
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = (logline?.title ?? (lang === 'en' ? 'screenplay' : '剧本')) + '.pdf'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="script-panel">
      {logline && (
        <div className="logline-box">
          <div className="logline-title">
            {t('梗要', 'Logline')}　{lang === 'en'
              ? `“${logline.title ?? 'Untitled'}”`
              : `《${logline.title ?? '未命名'}》`}
            {logline.title_en && logline.title_en !== logline.title ? ` (${logline.title_en})` : ''}
          </div>
          {logline.theme && <div className="logline-theme">{t('主题：', 'Theme: ')}{logline.theme}</div>}
          {logline.summary && <div className="logline-summary">{logline.summary}</div>}
        </div>
      )}
      <div className="panel-head">
        <span>{t('标准格式剧本', 'Standard format')}{payload.kind === 'script_check' ? t('（原稿）', ' (draft)') : ''}</span>
        <button className="panel-btn" data-filmy-download onClick={downloadPdf} disabled={busy}>
          {busy ? t('生成中…', 'Generating…') : t('下载 PDF', 'Download PDF')}
        </button>
      </div>
      <pre className="script-scroll">{script}</pre>
    </div>
  )
}
