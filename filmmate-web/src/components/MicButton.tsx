import { Mic, MicOff } from 'lucide-react'
import { cn } from '../lib/utils'
import { formatDuration } from '../lib/voiceInput'
import type { VoiceInputEngine, VoiceInputStatus } from '../hooks/useVoiceInput'
import { useI18n } from '../lib/i18n'

export interface MicButtonProps {
  status: VoiceInputStatus
  elapsedMs: number
  /** 流式回复中不能开始新录音。 */
  disabled?: boolean
  /** 环境不支持 MediaRecorder 时显示 MicOff 并禁用。 */
  supported?: boolean
  /** server = whisper 接口；browser = 浏览器原生识别。 */
  engine?: VoiceInputEngine
  onStart: () => void
  onStop: () => void
}

/**
 * Phase 2：语音输入（voice input）麦克风按钮。
 * 点击开始录音，再点一次停止并送 whisper-1；转写结果由 useVoiceInput 交回输入框，
 * 不会自动发送。Esc 取消录音（由 useVoiceInput 监听）。
 */
export function MicButton({
  status,
  elapsedMs,
  disabled = false,
  supported = true,
  engine = 'server',
  onStart,
  onStop,
}: MicButtonProps) {
  const { t } = useI18n()
  const recording = status === 'recording'
  const busy = status === 'requesting' || status === 'transcribing'

  const label = !supported
    ? '当前环境不支持录音'
    : recording
      ? `停止录音（已录 ${formatDuration(elapsedMs)}，Esc 取消）`
      : status === 'requesting'
        ? '等待麦克风权限…'
        : status === 'transcribing'
          ? '转写中…'
          : engine === 'browser'
            ? '语音输入（浏览器识别，无需 API）'
            : '语音输入（whisper-1）'

  return (
    <button
      type="button"
      className={cn('mic-btn', (recording || busy) && 'active')}
      onClick={() => {
        if (recording) onStop()
        else if (status === 'idle') onStart()
      }}
      disabled={disabled || busy || !supported}
      title={label}
      aria-label={label}
      aria-pressed={recording}
    >
      {supported ? <Mic size={17} /> : <MicOff size={17} />}
      {recording && <span className="mic-ring" aria-hidden />}
      {busy && <span className="mic-spinner" aria-hidden />}
    </button>
  )
}
