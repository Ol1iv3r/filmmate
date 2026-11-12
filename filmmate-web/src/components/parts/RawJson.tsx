import { useState } from 'react'
import { ChevronDown, Copy, Check } from 'lucide-react'
import { cn, copyText } from '../../lib/utils'

/** 可折叠原始 JSON 区（评委问“是不是假的”时直接展开）。 */
export function RawJson({
  title = '原始 JSON',
  data,
  defaultOpen = false,
}: {
  title?: string
  data: unknown
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(data, null, 2) ?? 'undefined'

  const onCopy = async () => {
    if (await copyText(json)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    }
  }

  return (
    <div className={cn('raw-json', open && 'open')}>
      <button className="raw-json-toggle" onClick={() => setOpen((o) => !o)}>
        <ChevronDown size={13} className={cn('chev', open && 'flip')} />
        <span>{title}</span>
        <span className="raw-json-hint">点击{open ? '收起' : '展开'}</span>
      </button>
      {open && (
        <div className="raw-json-body">
          <button className="icon-btn mini raw-json-copy" onClick={onCopy} title="复制 JSON">
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
          <pre>{json}</pre>
        </div>
      )}
    </div>
  )
}

/** 点击展开全文的段落。 */
export function ExpandableText({ text, max = 110 }: { text: string; max?: number }) {
  const [open, setOpen] = useState(false)
  const clamped = text.length > max
  return (
    <div className="expandable-text">
      <span className={cn('expandable-body', !open && clamped && 'clamp')}>{text}</span>
      {clamped && (
        <button className="link-btn" onClick={() => setOpen((o) => !o)}>
          {open ? '收起' : '展开'}
        </button>
      )}
    </div>
  )
}
