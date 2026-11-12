/**
 * Phase 2 语音输入（voice input）：MediaRecorder 容器选择。
 * Tauri 的 WebView 是 Chromium，webm/opus 一定可用；其余是兜底，
 * 以防以后跑在别的 WebView 里（Safari 只认 mp4）。
 */
export const AUDIO_MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
] as const

export function pickAudioMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return undefined
  }
  return AUDIO_MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type))
}

export function isRecordingSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined'
  )
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}
