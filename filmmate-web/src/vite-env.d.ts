/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_REMOTE_CONVERSATIONS?: string
  /** Phase 2：语音转写后端（POST /api/transcribe）。留空时回退到 VITE_API_BASE。 */
  readonly VITE_TRANSCRIBE_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
