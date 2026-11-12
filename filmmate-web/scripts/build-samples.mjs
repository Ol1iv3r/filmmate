/**
 * 从 _ref/AI-Project/AI-Project/samplesv*.json 生成前端的 Mock 样本数据。
 * 清洗说明：
 *  - 去掉 description 里混入的 [[00:01](https://youtube...)] 引用标记
 *  - 每条样本最多保留 6 个镜头段，控制体积
 *  - 跳过 mainkeywords.json（不是合法 JSON，本来就是逗号串）
 * 运行：npm run samples:build
 */
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(__dirname, '../../_ref/AI-Project/AI-Project')
const OUT = resolve(__dirname, '../src/mock/samples.json')

const REF_RE = /\[\[[^\]]*\]\]\(https?:\/\/[^)\s]+\)\s*/g

/** @type {any[]} */
const out = []
for (const file of readdirSync(SRC).sort()) {
  if (!/^samplesv\d+\.json$/.test(file)) continue
  const raw = JSON.parse(readFileSync(join(SRC, file), 'utf8'))
  const videoId = raw.youtube_video_id ?? ''
  const title = String(raw.title ?? file).slice(0, 120)
  const segments = (Array.isArray(raw.segments) ? raw.segments : [])
    .slice(0, 6)
    .map((seg) => ({
      time_start: String(seg.time_start ?? ''),
      time_end: String(seg.time_end ?? ''),
      description: String(seg.description ?? '').replace(REF_RE, '').replace(/\s+/g, ' ').trim(),
      keywords: Array.isArray(seg.keywords) ? seg.keywords.slice(0, 6) : [],
    }))
    .filter((seg) => seg.description.length > 0)
  if (videoId && title && segments.length > 0) {
    out.push({
      videoId,
      title,
      keywords: Array.isArray(raw.video_keywords) ? raw.video_keywords.slice(0, 10) : [],
      segments,
    })
  }
}

mkdirSync(dirname(OUT), { recursive: true })
writeFileSync(OUT, JSON.stringify(out))
console.log(`[samples:build] wrote ${out.length} samples, ${out.reduce((n, s) => n + s.segments.length, 0)} segments -> ${OUT}`)
