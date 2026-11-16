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
