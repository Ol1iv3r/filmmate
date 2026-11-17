/**
 * Capture README screenshots from the running app.
 *
 *   FILMMATE_URL=http://127.0.0.1:8010/ node scripts/capture-features.mjs
 *
 * Uses a fresh browser context, switches the UI to English, and exercises
 * inspiration, storyboard and shooting-plan flows in offline mode so the
 * capture is deterministic and does not consume model credits.
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const shots = resolve(here, '../../docs/screenshots')
mkdirSync(shots, { recursive: true })

const url = process.env.FILMMATE_URL ?? 'http://127.0.0.1:8010/'
const chrome = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

const browser = await chromium.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const errors = []
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`[console.error] ${message.text()}`)
})
page.on('pageerror', (error) => errors.push(`[pageerror] ${error.message}`))

const assistant = () => page.locator('.msg.assistant').last()
const waitIdle = () => page.waitForFunction(() => !document.querySelector('.stream-cursor'), null, { timeout: 60000 })
const shot = async (name) => {
  await page.screenshot({ path: resolve(shots, name), fullPage: false })
  console.log('saved', name)
}
const shotElement = async (name, locator, clean = false) => {
  if (clean) {
    await page.evaluate(() => document.body.classList.add('capture-clean'))
    await page.waitForTimeout(150)
  }
  await locator.screenshot({ path: resolve(shots, name) })
  if (clean) await page.evaluate(() => document.body.classList.remove('capture-clean'))
  console.log('saved', name)
}
const newChat = async () => {
  await page.locator('.new-chat-btn').click()
  await page.waitForSelector('.hero-title')
}
const chip = (label) => page.locator('.composer-area .quick-chips .quick-chip').filter({ hasText: label }).first()

try {
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForSelector('.hero-title')

  // English UI.
  if ((await page.locator('.lang-btn').innerText()).trim().toUpperCase() === 'EN') {
    await page.locator('.lang-btn').click()
  }
  await page.waitForFunction(() => document.documentElement.lang === 'en')
  await page.addStyleTag({
    content: 'body.capture-clean .topbar,body.capture-clean .composer-area,body.capture-clean .jump-bottom,body.capture-clean .filmy{display:none!important}',
  })

  // Give the default conversation an English title for the home screenshot.
  const rename = page.locator('.conv-item.active .conv-actions button').first()
  if (await rename.count()) {
    await page.locator('.conv-item.active').hover()
    await rename.click()
    const input = page.locator('.conv-rename-input')
    await input.fill('New chat')
    await input.press('Enter')
    await page.waitForTimeout(300)
  }
  await page.addStyleTag({ content: '.conv-time{display:none!important}' })
  await page.mouse.move(1100, 480)
  await page.waitForTimeout(300)
  await shot('feature-home.png')

  // Inspiration: genre -> feeling -> style/theme/film panel.
  await chip('Inspiration').click()
  await page.locator('.kind-chips .quick-chip').filter({ hasText: 'Film' }).first().click()
  await page.locator('textarea').fill('Hong Kong, rainy night, old buildings, loneliness')
  await page.locator('textarea').press('Enter')
  await page.waitForSelector('.insp-panel', { timeout: 60000 })
  await waitIdle()
  await shotElement('feature-inspiration.png', page.locator('.insp-film').first())

  // Storyboard: upload a script, choose the board, press Enter.
  await newChat()
  await page.locator('input[type=file]').setInputFiles('/tmp/filmmate_demo_script.txt')
  await page.waitForSelector('.composer-mode')
  await chip('Storyboard').click()
  await page.locator('textarea').press('Enter')
  await page.waitForSelector('.storyboard-panel', { timeout: 60000 })
  await waitIdle()
  await shotElement('feature-storyboard.png', page.locator('.tool-card').filter({ has: page.locator('.storyboard-panel') }).last(), true)

  // Shooting plan: latest storyboard + preferences -> days + .ics.
  await chip('Shooting plan').click()
  await page.locator('textarea').fill('3 days, 10 hours a day, avoid weekends')
  await page.locator('textarea').press('Enter')
  await page.waitForSelector('.schedule-panel', { timeout: 60000 })
  await waitIdle()
  await shotElement('feature-shooting-plan.png', page.locator('.tool-card').filter({ has: page.locator('.schedule-panel') }).last(), true)

  // Reference-film form: the fifth workflow.
  await newChat()
  await chip('Reference film').click()
  await page.waitForSelector('.ref-form')
  await shotElement('feature-reference-film.png', page.locator('.ref-form'))

  console.log('console/page errors:', errors.length)
  for (const error of errors) console.log('  ', error)
  if (errors.length) process.exitCode = 1
} finally {
  await browser.close()
}
