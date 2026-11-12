import { useCallback, useMemo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Check, Copy } from 'lucide-react'
import { cn, copyText } from '../lib/utils'

function textOf(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (typeof node === 'object' && 'props' in node) {
    const props = (node as { props?: { children?: ReactNode } }).props
    return textOf(props?.children)
  }
  return ''
}

function languageOf(node: ReactNode): string {
  if (typeof node !== 'object' || node === null || !Array.isArray(node)) return ''
  for (const child of node) {
    if (typeof child === 'object' && child !== null && 'props' in child) {
      const className = (child as { props?: { className?: string } }).props?.className ?? ''
      const m = className.match(/language-([\w+-]+)/)
      if (m) return m[1]
    }
  }
  return ''
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const code = useMemo(() => textOf(children), [children])
  const lang = useMemo(() => languageOf(children), [children])

  const onCopy = useCallback(async () => {
    if (await copyText(code)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    }
  }, [code])

  return (
    <div className="code-block">
      <div className="code-block-head">
        <span className="code-lang">{lang || 'text'}</span>
        <button className="icon-btn mini" onClick={onCopy} title="复制代码">
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  )
}

/** Markdown 渲染：GFM 表格/任务列表 + highlight.js 代码高亮 + 复制按钮。 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          code: ({ className, children }) =>
            className && (className.includes('language-') || className.includes('hljs')) ? (
              <code className={className}>{children}</code>
            ) : (
              <code className="inline-code">{children}</code>
            ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className={cn('md-quote')}>{children}</blockquote>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
