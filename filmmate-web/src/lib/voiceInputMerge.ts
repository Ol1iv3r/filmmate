/**
 * Phase 2 语音输入（voice input）：把转写结果放回用户已经输入的内容里。
 * 只补一个空格，不自动发送 —— 用户永远有机会先改再送。
 * 保持纯函数，方便单独测试。
 */
export function mergeTranscript(draft: string, transcript: string): string {
  const text = transcript.trim()
  if (!text) return draft
  if (!draft.trim()) return text
  return /\s$/.test(draft) ? `${draft}${text}` : `${draft.trimEnd()} ${text}`
}
