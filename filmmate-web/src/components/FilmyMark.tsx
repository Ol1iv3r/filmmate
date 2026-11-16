import { cn } from '../lib/utils'

/** Filmy 的简约 logo：黄色方块脸 + 三撮黑发 + 大眼睛 + 红腮红 + 微笑。 */
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
      <path d="M13 13 Q10 4 17 3 Q16 8 19 13" fill="#20232b" />
      <path d="M21 13 Q22 4 28 4 Q24 8 26 13" fill="#20232b" />
      <path d="M29 13 Q34 6 36 11 Q33 12 32 13" fill="#20232b" />
      <rect x="7" y="12" width="34" height="30" rx="8.5" fill="#f5d23c" stroke="#20232b" strokeWidth="2.2" />
      <ellipse cx="18" cy="26" rx="4.2" ry="5.2" fill="#fff" />
      <ellipse cx="30" cy="26" rx="4.2" ry="5.2" fill="#fff" />
      <path d="M16 23 Q20 22.5 20 26 Q20 29 17 28.6 Q18.6 27 18.6 26 Q18.6 24.6 16 23 Z" fill="#20232b" />
      <path d="M28 23 Q32 22.5 32 26 Q32 29 29 28.6 Q30.6 27 30.6 26 Q30.6 24.6 28 23 Z" fill="#20232b" />
      <circle cx="12.5" cy="31" r="2.4" fill="#e8483f" />
      <circle cx="35.5" cy="31" r="2.4" fill="#e8483f" />
      <path d="M19 33 Q24 38 29 33" fill="none" stroke="#20232b" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}
