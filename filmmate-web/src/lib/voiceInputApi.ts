/**
 * Phase 2 语音输入（voice input）：语音转文字（whisper-1）的浏览器端客户端。
 *
 * 密钥只在 Python 后端（config.py 读 .env），前端只上传音频字节：
 *
 *   POST {VITE_TRANSCRIBE_BASE}/api/transcribe
 *   multipart: file=<audio>, language=<可选>
 *   -> { text: string }
 *
 * 与 Electron 版 src/main/ipc/transcribe.ts 的区别只有传输方式；
 * 校验（25 MB / 空音频）和错误分类完全一致。
 */
import { API_BASE } from './transport'

const MAX_AUDIO_BYTES = 25 * 1024 * 1024
const TIMEOUT_MS = 60_000

export type TranscribeErrorCode =
  | 'NO_BACKEND'
  | 'EMPTY_AUDIO'
  | 'TOO_LARGE'
  | 'AUTH'
  | 'RATE_LIMIT'
  | 'PROVIDER'
  | 'TIMEOUT'
  | 'NETWORK'
  | 'UNKNOWN'

export type TranscribeResult =
  | { ok: true; text: string }
  | { ok: false; code: TranscribeErrorCode; message: string }

function fail(code: TranscribeErrorCode, message: string): TranscribeResult {
  return { ok: false, code, message }
}

/** 专用变量优先，其次复用聊天后端。 */
function baseUrl(): string | undefined {
  return (import.meta.env.VITE_TRANSCRIBE_BASE || API_BASE)?.replace(/\/$/, '')
}

function fileNameFor(blob: Blob): string {
  if (blob.type.includes('ogg')) return 'audio.ogg'
  if (blob.type.includes('mp4')) return 'audio.mp4'
  return 'audio.webm'
}

async function mapHttpError(response: Response): Promise<TranscribeResult> {
  let detail = ''
  try {
    const body = (await response.json()) as { detail?: unknown }
    detail = typeof body.detail === 'string' ? body.detail : ''
  } catch {
    /* 后端没回 JSON，用下面的默认文案 */
  }

  if (response.status === 401 || response.status === 403) {
    return fail('AUTH', detail || '转写服务密钥无效，请检查 .env 的 AI_GATEWAY_API_KEY。')
  }
  if (response.status === 413) {
    return fail('TOO_LARGE', detail || '录音超过 25 MB 上限，请缩短录音。')
  }
  if (response.status === 429) {
    return fail('RATE_LIMIT', detail || '转写请求过于频繁，请稍后重试。')
  }
  if (response.status === 504) {
    return fail('TIMEOUT', detail || '转写超时，请重试。')
  }
  return fail('PROVIDER', detail || `转写失败（HTTP ${response.status}）。`)
}

export async function transcribeAudio(blob: Blob, language?: string): Promise<TranscribeResult> {
  if (blob.size === 0) return fail('EMPTY_AUDIO', '没有录到声音，请重新录音。')
  if (blob.size > MAX_AUDIO_BYTES) {
    return fail('TOO_LARGE', '录音超过 25 MB 上限，请缩短录音。')
  }

  const base = baseUrl()
  if (base === undefined) {
    return fail(
      'NO_BACKEND',
      '未设置 VITE_TRANSCRIBE_BASE（或 VITE_API_BASE）。语音输入需要本地 Python 后端。',
    )
  }

  const form = new FormData()
  form.append('file', blob, fileNameFor(blob))
  if (language) form.append('language', language)

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const response = await fetch(`${base}/api/transcribe`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    })
    if (!response.ok) return mapHttpError(response)

    const data = (await response.json()) as { text?: unknown }
    const text = typeof data.text === 'string' ? data.text.trim() : ''
    if (!text) return fail('EMPTY_AUDIO', '没有识别出文字，请再试一次。')
    return { ok: true, text }
  } catch (error) {
    const name = (error as Error).name
    if (name === 'AbortError') return fail('TIMEOUT', '转写超时，请检查网络后重试。')
    return fail('NETWORK', `无法连接转写服务：${(error as Error).message}`)
  } finally {
    window.clearTimeout(timer)
  }
}
