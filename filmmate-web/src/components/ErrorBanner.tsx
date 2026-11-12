import { AlertTriangle, RotateCcw, X } from 'lucide-react'

/** 网络错误横幅 + 重试。 */
export function ErrorBanner({
  message,
  onRetry,
  onDismiss,
}: {
  message: string
  onRetry: () => void
  onDismiss: () => void
}) {
  return (
    <div className="error-banner" role="alert">
      <AlertTriangle size={15} />
      <span className="error-banner-text">连接出错了：{message || '网络错误'}</span>
      <button className="error-retry" onClick={onRetry}>
        <RotateCcw size={12} />
        重试
      </button>
      <button className="icon-btn mini error-close" onClick={onDismiss} title="关闭">
        <X size={12} />
      </button>
    </div>
  )
}
