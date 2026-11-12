/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_REMOTE_CONVERSATIONS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
