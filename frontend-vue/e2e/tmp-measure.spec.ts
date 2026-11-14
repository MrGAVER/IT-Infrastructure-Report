import { test } from '@playwright/test'
import { openApp, signInAsAdmin } from './fixtures.ts'

// ВРЕМЕННО (отладка Playwright 1.65): геометрия строки «новый пользователь» и её предков. Не попадает в main.
test.use({ viewport: { width: 390, height: 844 } })

test('геометрия поля пароля', async ({ page }) => {
  await signInAsAdmin(page)
  await openApp(page, '/settings')
  const data = await page.locator('.new-user-row input[type="password"]').first().evaluate((el) => {
    const r = (e: Element) => {
      const b = e.getBoundingClientRect()
      const s = getComputedStyle(e)
      return {
        node: e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : ''),
        w: Math.round(b.width * 100) / 100,
        cw: (e as HTMLElement).clientWidth,
        ow: (e as HTMLElement).offsetWidth,
        pad: `${s.paddingLeft}/${s.paddingRight}`,
        border: `${s.borderLeftWidth}/${s.borderRightWidth}`,
        box: s.boxSizing,
        display: s.display,
        overflowY: s.overflowY,
      }
    }
    const chain: unknown[] = []
    for (let n: Element | null = el; n && n !== document.documentElement; n = n.parentElement) chain.push(r(n))
    const form = el.closest('form')!
    return {
      inner: window.innerWidth,
      docClient: document.documentElement.clientWidth,
      docScrollH: document.documentElement.scrollHeight,
      innerH: window.innerHeight,
      chain,
      siblings: Array.from(form.children).map(r),
    }
  })
  console.log('GEOM ' + JSON.stringify(data))
})
