import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { seedDiagram } from './seed.ts'

// Каркас на телефоне и высота экрана диаграммы (ревью 2.158.0, поток «исполнитель 1»): UI-05.

test.describe('UI-05: шапка и высота холста диаграммы', () => {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 390, height: 667 },
    { width: 1440, height: 900 },
  ]) {
    test(`страница диаграммы не прокручивается, холст не короче 320 px — ${viewport.width}×${viewport.height}`, async ({ page, request }) => {
      await page.setViewportSize(viewport)
      const id = await seedDiagram(request, { devices: 12 })
      await openApp(page, `/diagrams/${id}`)
      await page.locator('.vue-flow__node').first().waitFor()

      // Раньше height: calc(100vh - 96px) давал прокрутку документа (+22 px на 900 и +59 px на 844), а 100vh на мобильных
      // браузерах ещё и «прыгает» вместе с адресной строкой.
      const { scrollHeight, innerHeight, canvasHeight } = await page.evaluate(() => ({
        scrollHeight: document.documentElement.scrollHeight,
        innerHeight: window.innerHeight,
        canvasHeight: document.querySelector('.canvas-wrap')!.getBoundingClientRect().height,
      }))
      expect(canvasHeight).toBeGreaterThanOrEqual(320)
      // Только на низком окне (667), где одной тулбар-обёртки уже почти хватает на всё, прокрутка допустима из-за min-height холста.
      if (viewport.height >= 844) expect(scrollHeight).toBeLessThanOrEqual(innerHeight)
    })
  }

  test.describe('телефон 390×844', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('шапка с длинным заголовком занимает не больше 80 px, крошки скрыты', async ({ page }) => {
      await openApp(page, '/devices')
      const topbar = await page.locator('.topbar').evaluate((el) => el.getBoundingClientRect().height)
      // Было ≈ 125 px (15 % окна) на заголовке «Инвентаризация физических устройств».
      expect(topbar).toBeLessThanOrEqual(80)
      await expect(page.locator('.topbar .crumb')).toBeHidden()
      await expect(page.locator('.topbar .page-title')).toBeVisible()
    })

    test('высота шапки передаётся в --topbar-h и совпадает с фактической', async ({ page }) => {
      await openApp(page, '/devices')
      const { declared, actual } = await page.evaluate(() => ({
        declared: parseFloat(getComputedStyle(document.querySelector('.app-shell')!).getPropertyValue('--topbar-h')),
        actual: document.querySelector('.topbar')!.getBoundingClientRect().height,
      }))
      expect(Math.abs(declared - actual)).toBeLessThanOrEqual(1)
    })
  })
})
