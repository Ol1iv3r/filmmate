import { useEffect, useRef, useState } from 'react'
import { MessageSquarePlus, Trash2, Pencil, Check, X, PanelLeftClose } from 'lucide-react'
import { FilmyMark } from './FilmyMark'
import type { ConversationMeta } from '../lib/conversations'
import { cn, formatTimeAgo } from '../lib/utils'
import { isMockMode } from '../lib/transport'
import { useI18n } from '../lib/i18n'

/**
 * 会话侧栏：新建 / 切换 / {t('重命名', 'Rename')} / {t('删除', 'Delete')}。
 * 列表 UI 属于 Phase 1；数据存取走 ConversationRepository（现在 localStorage，
 * Jacky Phase 3 的 JSON 落盘 API 好了之后自动切换）。
 */
export function Sidebar({
  open,
  onClose,
  conversations,
  activeId,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: {
  open: boolean
  onClose: () => void
  conversations: ConversationMeta[]
  activeId: string | null
  onNew: () => void
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const { t } = useI18n()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const editRef = useRef<HTMLInputElement>(null)
  const confirmTimer = useRef<number | null>(null)

  useEffect(() => {
    if (editingId) editRef.current?.select()
  }, [editingId])

  const startRename = (c: ConversationMeta) => {
    setEditingId(c.id)
    setEditText(c.title)
  }
  const commitRename = (id: string) => {
    const t = editText.trim()
    if (t) onRename(id, t)
    setEditingId(null)
  }

  const askDelete = (id: string) => {
    if (confirmId === id) {
      onDelete(id)
      setConfirmId(null)
      return
    }
    setConfirmId(id)
    if (confirmTimer.current) window.clearTimeout(confirmTimer.current)
    confirmTimer.current = window.setTimeout(() => setConfirmId(null), 3000)
  }

  return (
    <>
      <div className={cn('sidebar-overlay', open && 'show')} onClick={onClose} />
      <aside className={cn('sidebar', open && 'open')}>
        <div className="sidebar-head">
          <div className="brand">
            <span className="brand-logo">
              <FilmyMark size={22} />
            </span>
            <div className="brand-text">
              <span className="brand-name">Filmmate</span>
              <span className="brand-tag">{t('影视创作 AI 助理', 'AI film assistant')}</span>
            </div>
          </div>
          <button className="icon-btn sidebar-close" onClick={onClose} title={t('收起侧栏', 'Close sidebar')}>
            <PanelLeftClose size={15} />
          </button>
        </div>

        <button className="new-chat-btn" onClick={onNew}>
          <MessageSquarePlus size={15} />
          {t('新建对话', 'New chat')}
          <kbd>⌘K</kbd>
        </button>

        <div className="conv-list-label">{t('对话历史', 'Chats')}</div>
        <nav className="conv-list">
          {conversations.length === 0 && <div className="conv-empty">{t('还没有对话，先发一条试试。', 'No chats yet. Send the first message.')}</div>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={cn('conv-item', activeId === c.id && 'active', confirmId === c.id && 'confirming')}
              onClick={() => onSelect(c.id)}
            >
              {editingId === c.id ? (
                <input
                  ref={editRef}
                  className="conv-rename-input"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(c.id)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={() => commitRename(c.id)}
                />
              ) : (
                <span className="conv-title" title={c.title}>
                  {c.title}
                </span>
              )}
              <span className="conv-time">{formatTimeAgo(c.updatedAt)}</span>
              <span className="conv-actions" onClick={(e) => e.stopPropagation()}>
                {editingId === c.id ? (
                  <button className="icon-btn mini" onClick={() => commitRename(c.id)} title={t('确定', 'Confirm')}>
                    <Check size={12} />
                  </button>
                ) : (
                  <button className="icon-btn mini" onClick={() => startRename(c)} title={t('重命名', 'Rename')}>
                    <Pencil size={12} />
                  </button>
                )}
                <button
                  className={cn('icon-btn mini', 'danger', confirmId === c.id && 'armed')}
                  onClick={() => askDelete(c.id)}
                  title={confirmId === c.id ? t('再点一次确认删除', 'Click again to delete') : t('删除对话', 'Delete conversation')}
                >
                  {confirmId === c.id ? <X size={12} /> : <Trash2 size={12} />}
                </button>
              </span>
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className={cn('mode-badge', isMockMode ? 'mock' : 'live')}>
            <span className="mode-dot" />
            {isMockMode ? t('本地演示模式', 'Local demo') : t('API 在线模式', 'API online')}
          </span>
          <span className="sidebar-version">COMP4431 · Group 20</span>
        </div>
      </aside>
    </>
  )
}
