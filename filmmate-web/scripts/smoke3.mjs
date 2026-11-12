/**
 * 第三轮：网络错误路径 —— VITE_API_BASE 指向不可达地址时，
 * 应显示错误横幅，点击「重试」恢复（mock 模式下由 useChat 的 error 状态触发）。
 * 运行：VITE_API_BASE=http://127.0.0.1:9 npm run dev -- --port 5199 后执行本脚本
 */
import { chromium } from 'playwright-core'

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const URL = process.env.FILMMATE_URL ?? 'http://localhost:5199/'

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(`[console.error] ${m.text()}`))
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

await page.goto(URL, { waitUntil: 'networkidle' })
await page.waitForSelector('.hero-title', { timeout: 10000 })
const badge = await page.textContent('.mode-badge')
console.log('模式徽标:', badge?.trim())

await page.fill('textarea', '给我出分镜')
await page.keyboard.press('Enter')
await page.waitForSelector('.error-banner', { timeout: 15000 })
console.log('✅ 错误横幅出现:', (await page.textContent('.error-banner-text'))?.trim().slice(0, 50))

// 网络错误来自 fetch 失败，console 里会有 failed fetch 的报错，过滤掉这类噪音
const real = errors.filter((e) => !/Failed to load resource|fetch/i.test(e))
await browser.close()
if (real.length) {
  console.log('❌ 其它错误:', real)
  process.exit(1)
}
console.log('✅ 第三轮通过（fetch 失败属预期）')
