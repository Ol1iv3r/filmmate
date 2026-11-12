/**
 * 视觉/运行时冒烟测试：用本机 Chrome 驱动页面，走一遍完整演示链路：
 *   空态 → 发一条“出分镜”消息 → 观察工具卡片生命周期 → 完成态（命中样本 + 原始 JSON）
 * 输出截图到 .shots/，并把 console 错误打到 stdout。
 * 运行：node scripts/smoke.mjs
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SHOTS = resolve(__dirname, '../.shots')
mkdirSync(SHOTS, { recursive: true })

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const URL = process.env.FILMMATE_URL ?? 'http://localhost:5173/'

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const errors = []
page.on('console', (msg) => {
  if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`)
})
page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`))

const shot = (name) => page.screenshot({ path: resolve(SHOTS, name) })

console.log('1) 打开空态…')
await page.goto(URL, { waitUntil: 'networkidle' })
await page.waitForSelector('.hero-title', { timeout: 10000 })
await shot('01-empty.png')

console.log('2) 点击示例卡填入「出分镜」…')
await page.click('.example-card:first-child')
await page.waitForTimeout(300)
const filled = await page.inputValue('textarea')
console.log('   输入框内容长度:', filled.length)
await shot('02-filled.png')

console.log('3) 发送（Enter）…')
await page.keyboard.press('Enter')
await page.waitForSelector('.tool-card', { timeout: 8000 })
await page.waitForTimeout(900)
await shot('03-tool-running.png')
const runningStatus = await page.textContent('.tool-card .tool-status')
console.log('   工具卡片状态:', runningStatus?.trim())

console.log('4) 等待工具完成（命中样本出现）…')
await page.waitForSelector('.tool-card.state-done', { timeout: 15000 })
await page.waitForSelector('.hit-row', { timeout: 15000 })
await shot('04-tool-done.png')
const doneStatus = await page.textContent('.tool-card .tool-status')
console.log('   完成状态:', doneStatus?.trim())
const hitCount = await page.locator('.hit-row').count()
console.log('   命中样本数:', hitCount)

console.log('5) 展开原始 JSON …')
await page.click('.json-toggle')
await page.waitForSelector('.raw-json-body', { timeout: 5000 })
await page.waitForTimeout(200)
await shot('05-raw-json.png')

console.log('6) 等回答流完…')
await page.waitForFunction(() => !document.querySelector('.stream-cursor'), null, { timeout: 30000 })
await page.waitForTimeout(400)
await shot('06-answer.png')
const hasTable = await page.locator('.markdown table').count()
const hasQuote = await page.locator('.md-quote').count()
console.log('   表格数:', hasTable, '| 引用块数:', hasQuote)

console.log('7) 重新生成…')
await page.hover('.msg.assistant .msg-actions')
await page.click('button[title="重新生成"]')
await page.waitForSelector('.tool-card.state-done', { timeout: 15000 })
console.log('   重新生成 OK')

console.log('8) 侧栏会话列表…')
const convCount = await page.locator('.conv-item').count()
console.log('   会话数:', convCount)
await shot('07-sidebar.png')

console.log('9) 新建会话 + 空态回显…')
await page.click('.new-chat-btn')
await page.waitForSelector('.hero-title', { timeout: 8000 })
const convCount2 = await page.locator('.conv-item').count()
console.log('   新建后会话数:', convCount2)
await shot('08-new-chat.png')

console.log('10) 模拟错误路径（错误演示 触发工具失败）…')
await page.fill('textarea', '错误演示：给我分镜')
await page.keyboard.press('Enter')
await page.waitForSelector('.tool-card.state-error', { timeout: 15000 })
await shot('09-tool-error.png')
const errText = await page.textContent('.tool-error-text')
console.log('   错误文案:', errText?.trim().slice(0, 60))

console.log('11) 会话切换与持久化（刷新页面）…')
await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('.conv-item', { timeout: 10000 })
await page.waitForSelector('.msg.assistant', { timeout: 10000 })
console.log('   刷新后消息仍在：OK')

await shot('10-persist.png')
await browser.close()

if (errors.length) {
  console.log('\n❌ 发现错误:')
  for (const e of errors) console.log('  ', e)
  process.exit(1)
} else {
  console.log('\n✅ 全部通过，无 console 错误')
}
