import { cn } from '../lib/utils'

/** Filmy 的极简 logo：黄色圆角方块 + 两只点状眼睛 + 小微笑。 */
export function FilmyMark({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <svg className={cn('filmy-mark', className)} width={size} height={size} viewBox="0 0 48 48" role="img" aria-label="Filmy">
      <rect x="7" y="7" width="34" height="34" rx="9" fill="#f5d23c" stroke="#20232b" strokeWidth="2.2" />
      <circle cx="18" cy="24" r="2.7" fill="#20232b" />
      <circle cx="30" cy="24" r="2.7" fill="#20232b" />
      <circle cx="18.9" cy="23.2" r=".9" fill="#fff8ea" />
      <circle cx="30.9" cy="23.2" r=".9" fill="#fff8ea" />
      <path d="M19 31 Q24 35 29 31" fill="none" stroke="#20232b" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}
