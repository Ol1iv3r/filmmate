/**
 * 第二轮冒烟：移动端布局 / 多工具时间线 / 停止生成 / 侧栏重命名与删除 / 溢出检查。
 * 运行：node scripts/smoke2.mjs
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

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] })
const errors = []
const attach = (p) => {
  p.on('console', (m) => m.type() === 'error' && errors.push(`[console.error] ${m.text()}`))
  p.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))
}

const shot = (page, name) => page.screenshot({ path: resolve(SHOTS, name) })
const fail = (msg) => {
  console.log(`❌ ${msg}`)
  errors.push(msg)
}
const ok = (msg) => console.log(`✅ ${msg}`)

// ── 桌面：多工具时间线（剧本检查意图 → searchKnowledge + searchSamples） ──
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  attach(page)
  await page.goto(URL, { waitUntil: 'networkidle' })
  await page.waitForSelector('.hero-title', { timeout: 10000 })
  await page.fill('textarea', '帮我检查剧本漏洞：第1场 天台 夜 小明：今晚的月亮真圆。第2场 天台 日 小明：你不是出国了吗？')
  await page.keyboard.press('Enter')
  await page.waitForSelector('.tool-card', { timeout: 8000 })
  await page.waitForSelector('.tool-card.state-done', { timeout: 20000 })
  const cards = await page.locator('.tool-card').count()
  const names = await page.locator('.tool-card .tool-fn').allTextContents()
  if (cards === 2) ok(`多工具时间线：${cards} 张卡片，顺序 ${names.join(' → ')}`)
  else fail(`预期 2 张工具卡片，实际 ${cards}`)
  await page.waitForFunction(() => !document.querySelector('.stream-cursor'), null, { timeout: 30000 })
  await shot(page, '11-review-timeline.png')

  // 停止生成
  await page.fill('textarea', '给一个 30 秒可爱宠物广告出分镜，参考样本库')
  await page.keyboard.press('Enter')
  await page.waitForSelector('.tool-card', { timeout: 8000 })
  await page.click('.send-btn.stop')
  await page.waitForFunction(() => document.querySelector('.send-btn:not(.stop)'), null, { timeout: 8000 })
  ok('停止生成：流式被中止，按钮恢复发送态')

  // 重命名
  const firstTitle = await page.textContent('.conv-item .conv-title')
  await page.hover('.conv-item')
  await page.click('.conv-item .conv-actions button[title="重命名"]')
  await page.fill('.conv-rename-input', '我的分镜测试')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(300)
  const newTitle = await page.textContent('.conv-item .conv-title')
  if (newTitle?.trim() === '我的分镜测试') ok(`重命名：${firstTitle?.trim()} → ${newTitle.trim()}`)
  else fail(`重命名失败：${newTitle}`)

  // 溢出检查
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  if (overflow <= 0) ok('桌面布局无横向溢出')
  else fail(`桌面横向溢出 ${overflow}px`)
  await page.close()
}

// ── 移动端 390×844 ──
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  attach(page)
  await page.goto(URL, { waitUntil: 'networkidle' })
  await page.waitForSelector('.hero-title', { timeout: 10000 })
  const menuVisible = await page.locator('.menu-btn').isVisible()
  const sidebarHidden = !(await page.locator('.sidebar').evaluate((el) => getComputedStyle(el).transform.includes('0') && el.classList.contains('open')))
  if (menuVisible) ok('移动端：菜单按钮可见')
  else fail('移动端菜单按钮不可见')
  await page.click('.menu-btn')
  await page.waitForTimeout(400)
  const sidebarOpen = await page.locator('.sidebar').evaluate((el) => el.classList.contains('open'))
  if (sidebarOpen) ok('移动端：侧栏抽屉打开')
  else fail('移动端侧栏未打开')
  await shot(page, '12-mobile-sidebar.png')
  await page.mouse.click(350, 420) // 点侧栏之外的遮罩区域
  await page.waitForTimeout(400)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow <= 0) ok('移动端布局无横向溢出')
  else fail(`移动端横向溢出 ${overflow}px`)
  // 发一条消息
  await page.fill('textarea', '排一个 2 小时拍摄 rundown')
  await page.keyboard.press('Enter')
  await page.waitForSelector('.tool-card.state-done', { timeout: 20000 })
  await page.waitForFunction(() => !document.querySelector('.stream-cursor'), null, { timeout: 30000 })
  await shot(page, '13-mobile-chat.png')
  await page.close()
}

await browser.close()
if (errors.length) {
  console.log('\n❌ 第二轮有失败项：')
  for (const e of errors) console.log('  ', e)
  process.exit(1)
} else {
  console.log('\n✅ 第二轮全部通过')
}
