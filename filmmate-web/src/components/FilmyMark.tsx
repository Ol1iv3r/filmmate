import { cn } from '../lib/utils'

/** Filmy 的简约 logo：只剩头部轮廓 + 眼睛 + 微笑，用于顶栏/侧栏品牌位。 */
export function FilmyMark({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <svg
      className={cn('filmy-mark', className)}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-label="Filmy"
    >
      <rect x="7" y="10" width="34" height="30" rx="13" fill="#f5b84c" />
      <circle cx="18" cy="24" r="2.6" fill="#20232b" />
      <circle cx="30" cy="24" r="2.6" fill="#20232b" />
      <circle cx="18.9" cy="23.2" r=".8" fill="#fff8ea" />
      <circle cx="30.9" cy="23.2" r=".8" fill="#fff8ea" />
      <path d="M19 31 Q24 35 29 31" fill="none" stroke="#20232b" strokeWidth="2" strokeLinecap="round" />
      <path d="M11 18 Q14 15 18 15" fill="none" stroke="#e09b32" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}
