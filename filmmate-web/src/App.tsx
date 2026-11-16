import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Menu, Clapperboard } from 'lucide-react'
import { Sidebar } from './components/Sidebar'
import { useI18n } from './lib/i18n'
import { ChatPanel } from './components/ChatPanel'
import { createRepository, type ConversationMeta, type ConversationRepository } from './lib/conversations'
import { uid } from './lib/utils'

/**
 * 应用骨架：侧栏（会话列表）+ 聊天面板。
 * 会话数据统一走 ConversationRepository；ChatPanel 只报告自动标题，
 * 手动改名的标题不会被自动标题覆盖。
 */
export default function App() {
  const { lang, toggle, t } = useI18n()
  const repository = useMemo<ConversationRepository>(() => createRepository(), [])
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [booting, setBooting] = useState(true)
  const bootedRef = useRef(false)

  const refreshList = useCallback(async () => {
    const list = await repository.list()
    setConversations(list)
    return list
  }, [repository])

  const createConversation = useCallback(async (): Promise<string> => {
    const id = uid('conv')
    const meta = await repository.save(id, [])
    setConversations((prev) => [meta, ...prev])
    setActiveId(id)
    setSidebarOpen(false)
    return id
  }, [repository])

  // 启动：读会话列表；没有会话就建一个空的
  useEffect(() => {
    if (bootedRef.current) return
    bootedRef.current = true
    void (async () => {
      try {
        const list = await refreshList()
        if (list.length > 0) {
          setActiveId(list[0].id)
        } else {
          await createConversation()
        }
      } catch {
        // 存储不可用也照常进入，创建内存会话
        const id = uid('conv')
        setActiveId(id)
      } finally {
        setBooting(false)
      }
    })()
  }, [refreshList, createConversation])

  const handleNew = useCallback(() => {
    void createConversation()
  }, [createConversation])

  const handleSelect = useCallback((id: string) => {
    setActiveId(id)
    setSidebarOpen(false)
  }, [])

  const handleRename = useCallback(
    async (id: string, title: string) => {
      await repository.rename(id, title)
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)))
    },
    [repository],
  )

  const handleDelete = useCallback(
    async (id: string) => {
      await repository.remove(id)
      const rest = conversations.filter((c) => c.id !== id)
      setConversations(rest)
      if (activeId === id) {
        if (rest.length > 0) setActiveId(rest[0].id)
        else void createConversation()
      }
    },
    [repository, conversations, activeId, createConversation],
  )

  // ChatPanel 报告自动标题：只在还是「新对话」时采用
  const handleAutoTitle = useCallback((id: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id && (c.title === '新对话' || !c.title) ? { ...c, title } : c)),
    )
  }, [])

  // ⌘K / Ctrl+K 新建对话
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        void createConversation()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [createConversation])

  const activeTitle = conversations.find((c) => c.id === activeId)?.title ?? 'Filmmate'

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        conversations={conversations}
        activeId={activeId}
        onNew={handleNew}
        onSelect={handleSelect}
        onRename={(id, t) => void handleRename(id, t)}
        onDelete={(id) => void handleDelete(id)}
      />

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} title="打开侧栏">
            <Menu size={17} />
          </button>
          <div className="topbar-title">
            <Clapperboard size={14} className="topbar-logo" />
            <span>{activeTitle}</span>
          </div>
          <div className="topbar-right">
            <span className="topbar-hint">{t('深色影院模式 · 流式渲染 · 工具调用可视化', 'Dark cinema mode · Streaming · Tool calls visualized')}</span>
            <button
              className="lang-btn"
              onClick={toggle}
              title={t('切换为英文界面', 'Switch to Chinese')}
              aria-label={t('切换为英文界面', 'Switch to Chinese')}
            >
              {lang === 'zh' ? 'EN' : '中文'}
            </button>
          </div>
        </header>

        <div className="panel-wrap">
          {booting || !activeId ? (
            <div className="booting">{t('正在装载放映机…', 'Loading the projector…')}</div>
          ) : (
            <ChatPanel key={activeId} conversationId={activeId} onAutoTitle={handleAutoTitle} />
          )}
        </div>
      </div>
    </div>
  )
}
