import { expect, test, type Page } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { seedDiagram } from './seed.ts'

// Экран диаграммы на заполненных данных (ревью 2.158.0, поток «исполнитель 1»): UI-01 — граф вписан в холст при открытии.
// Нужна именно заполненная база: на пустой диаграмме нечего вписывать.

/** Все ли узлы Vue Flow лежат внутри .canvas-wrap (допуск 1 px) — критерий приёмки UI-01. */
async function allNodesInsideCanvas(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const canvas = document.querySelector('.canvas-wrap')!.getBoundingClientRect()
    const nodes = Array.from(document.querySelectorAll('.vue-flow__node'))
    if (nodes.length === 0) return false
    return nodes.every((node) => {
      const r = node.getBoundingClientRect()
      return r.left >= canvas.left - 1 && r.right <= canvas.right + 1 && r.top >= canvas.top - 1 && r.bottom <= canvas.bottom + 1
    })
  })
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test.describe(`диаграмма ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport })

    test('UI-01: после открытия все узлы лежат внутри холста', async ({ page, request }) => {
      const id = await seedDiagram(request)
      await openApp(page, `/diagrams/${id}`)
      await page.locator('.vue-flow__node').first().waitFor()
      // Без этого условия тест ничего бы не доказывал: граф обязан быть достаточно большим.
      expect(await page.locator('.vue-flow__node').count()).toBeGreaterThanOrEqual(25)
      await expect.poll(() => allNodesInsideCanvas(page), { message: 'узлы выходят за границы холста' }).toBe(true)
    })
  })
}
