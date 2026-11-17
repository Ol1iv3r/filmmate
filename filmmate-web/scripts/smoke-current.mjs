/**
 * Current-UI smoke test (production build served by FastAPI).
 *
 *   FILMMATE_URL=http://127.0.0.1:8000 node scripts/smoke-current.mjs
 *
 * Opens the home screen, sends a greeting through the real /api/chat path,
 * waits for the assistant answer, captures screenshots and fails on console
 * or page errors. Uses the local Chrome installation (no browser download).
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const shots = resolve(here, '../.shots')
mkdirSync(shots, { recursive: true })

const url = process.env.FILMMATE_URL ?? 'http://127.0.0.1:8000/'
const chrome = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: ['--no-sandbox'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const errors = []
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`[console.error] ${message.text()}`)
})
page.on('pageerror', (error) => errors.push(`[pageerror] ${error.message}`))

try {
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForSelector('.hero-title', { timeout: 15000 })
  await page.screenshot({ path: resolve(shots, 'current-home.png'), fullPage: false })

  const textarea = page.locator('textarea').first()
  await textarea.fill('你好')
  await textarea.press('Enter')

  await page.waitForSelector('.msg.assistant .markdown', { timeout: 30000 })
  await page.waitForFunction(() => !document.querySelector('.stream-cursor'), null, { timeout: 30000 })
  const answer = (await page.locator('.msg.assistant .markdown').last().innerText()).trim()
  if (!answer) throw new Error('assistant answer is empty')
  await page.screenshot({ path: resolve(shots, 'current-chat.png'), fullPage: false })

  console.log('assistant answer:', answer.slice(0, 120).replace(/\s+/g, ' '))
  console.log('console/page errors:', errors.length)
  for (const error of errors) console.log('  ', error)
  if (errors.length) process.exitCode = 1
} finally {
  await browser.close()
}
