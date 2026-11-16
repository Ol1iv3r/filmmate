import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Lang = 'zh' | 'en'

const STORAGE_KEY = 'filmmate.lang'

interface I18nContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  toggle: () => void
  /** t('中文', 'English') —— 按当前语言取值。 */
  t: (zh: string, en: string) => string
}

const I18nContext = createContext<I18nContextValue>({
  lang: 'zh',
  setLang: () => {},
  toggle: () => {},
  t: (zh) => zh,
})

function readInitial(): Lang {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    if (v === 'en' || v === 'zh') return v
  } catch {
    /* ignore */
  }
  return 'zh'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readInitial)

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
  }, [])

  const toggle = useCallback(() => {
    setLang(lang === 'zh' ? 'en' : 'zh')
  }, [lang, setLang])

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLang, toggle, t: (zh, en) => (lang === 'zh' ? zh : en) }),
    [lang, setLang, toggle],
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext)
}


const EN_CMD = /(?:切换到|切换成|切换|切到|改成|改为|换成|换到|使用|用|说|讲|回答|回复|输出|生成|翻译成)\s*(?:英文|英语|english)|(?:英文|英语|english)\s*(?:回答|回复|输出|写|生成|模式)|switch\s+to\s+english|in\s+english|english\s+please|use\s+english/gi
const ZH_CMD = /(?:切换到|切换成|切换|切到|改成|改为|换成|换到|使用|用|说|讲|回答|回复|输出|生成|翻译成)\s*(?:中文|汉语|chinese)|(?:中文|汉语|chinese)\s*(?:回答|回复|输出|写|生成|模式)|switch\s+to\s+chinese|in\s+chinese|chinese\s+please|use\s+chinese/gi

/** 识别聊天里的「切换英文 / 用中文回答 / switch to English」等指令。 */
export function detectLangCommand(text: string): Lang | null {
  const value = text || ''
  const last = (re: RegExp) => {
    let end = -1
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(value)) !== null) end = m.index + m[0].length
    return end
  }
  const en = last(EN_CMD)
  const zh = last(ZH_CMD)
  if (en < 0 && zh < 0) return null
  if (en >= 0 && zh >= 0) return en > zh ? 'en' : 'zh'
  return en >= 0 ? 'en' : 'zh'
}
