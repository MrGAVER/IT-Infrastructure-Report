import { expect, test, type Page } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { cleanupSeeded, seedDiagram, seedParallelLinks } from './seed.ts'

// Данные, созданные фикстурами, убираются после каждого теста — иначе они остаются в общей базе и меняют чужие проверки.
test.afterEach(async ({ request }) => {
  await cleanupSeeded(request)
})

// Экран диаграммы на заполненных данных (ревью 2.158.0, поток «исполнитель 1»): UI-01 — граф вписан в холст при открытии,
// UI-02 — есть кнопки масштаба и «вписать», на десктопе мини-карта, UI-22 — подписи портов не накладываются. Нужна именно заполненная база: на пустой диаграмме
// нечего вписывать и не по чему ориентироваться.

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

/** Текущий масштаб холста из матрицы transform панели Vue Flow. */
async function canvasScale(page: Page): Promise<number> {
  return page.evaluate(() => {
    const matrix = new DOMMatrix(getComputedStyle(document.querySelector('.vue-flow__transformationpane')!).transform)
    return matrix.a
  })
}

/** Сколько пар «подпись порта — подпись порта» и «подпись порта — узел» пересекаются (по ограничивающим прямоугольникам). */
async function labelOverlaps(page: Page): Promise<{ labels: number; labelLabel: number; labelNode: number }> {
  return page.evaluate(() => {
    const visible = (el: Element) => getComputedStyle(el).display !== 'none'
    const labels = Array.from(document.querySelectorAll('.diagram-edge-label--port')).filter(visible).map((el) => el.getBoundingClientRect())
    const nodes = Array.from(document.querySelectorAll('.vue-flow__node-device')).map((el) => el.getBoundingClientRect())
    const hit = (a: DOMRect, b: DOMRect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
    let labelLabel = 0
    let labelNode = 0
    labels.forEach((label, i) => {
      for (let j = i + 1; j < labels.length; j++) if (hit(label, labels[j])) labelLabel++
      if (nodes.some((node) => hit(label, node))) labelNode++
    })
    return { labels: labels.length, labelLabel, labelNode }
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

    test('UI-02: кнопки «Увеличить», «Уменьшить», «Показать всю диаграмму» работают и подписаны по-русски', async ({ page, request }) => {
      const id = await seedDiagram(request)
      await openApp(page, `/diagrams/${id}`)
      await expect.poll(() => allNodesInsideCanvas(page)).toBe(true)

      const controls = page.getByRole('group', { name: 'Масштаб диаграммы' })
      await expect(controls).toBeVisible()
      const fitScale = await canvasScale(page)

      await controls.getByRole('button', { name: 'Увеличить масштаб' }).click()
      await expect.poll(() => canvasScale(page)).toBeGreaterThan(fitScale)
      await controls.getByRole('button', { name: 'Уменьшить масштаб' }).click()
      await controls.getByRole('button', { name: 'Уменьшить масштаб' }).click()
      await expect.poll(() => canvasScale(page)).toBeLessThan(fitScale)

      await controls.getByRole('button', { name: 'Показать всю диаграмму' }).click()
      await expect.poll(() => allNodesInsideCanvas(page), { message: '«Показать всю диаграмму» не вернула граф в холст' }).toBe(true)
    })

    test('UI-02: мини-карта есть на десктопе и скрыта на телефоне, не перекрывая кнопки масштаба', async ({ page, request }) => {
      const id = await seedDiagram(request)
      await openApp(page, `/diagrams/${id}`)
      await expect.poll(() => allNodesInsideCanvas(page)).toBe(true)

      const minimap = page.locator('.vue-flow__minimap')
      if (viewport.width >= 1000) {
        await expect(minimap).toBeVisible()
        // Пакет выводит подпись как <title> внутри <svg role="img" aria-labelledby>, а не атрибутом корня.
        await expect(minimap.getByRole('img', { name: 'Мини-карта диаграммы' })).toBeVisible()
        expect(await minimap.locator('.vue-flow__minimap-node').count()).toBeGreaterThanOrEqual(25)
        const controlsBox = await page.getByRole('group', { name: 'Масштаб диаграммы' }).boundingBox()
        const minimapBox = await minimap.boundingBox()
        expect(minimapBox!.x).toBeGreaterThanOrEqual(controlsBox!.x + controlsBox!.width)
      } else {
        await expect(minimap).toHaveCount(0)
      }
    })

    test('UI-22: три параллельные связи свёрнуты в «×3»: один набор подписей вместо трёх', async ({ page, request }) => {
      const id = await seedParallelLinks(request, { links: 3 })
      await openApp(page, `/diagrams/${id}`)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(3)
      await expect(page.locator('.diagram-edge-label--mid')).toHaveCount(1)
      await expect(page.locator('.diagram-edge-label--mid')).toHaveText('×3')
      await expect(page.locator('.diagram-edge-label--port')).toHaveCount(2) // два конца первой связи, а не шесть
    })

    test('UI-22: две параллельные связи у соседних портов — подписи не пересекаются друг с другом и не заходят на узлы', async ({ page, request }) => {
      const id = await seedParallelLinks(request, { links: 2 })
      await openApp(page, `/diagrams/${id}`)
      await expect(page.locator('.diagram-edge-label--port')).toHaveCount(4) // группировки ещё нет: порог — три связи
      await expect.poll(() => labelOverlaps(page)).toEqual({ labels: 4, labelLabel: 0, labelNode: 0 })
    })

    test('UI-22: на мелком масштабе (< 0,6) подписи рёбер скрыты, при увеличении возвращаются', async ({ page, request }) => {
      const id = await seedParallelLinks(request, { links: 2 })
      await openApp(page, `/diagrams/${id}`)
      const controls = page.getByRole('group', { name: 'Масштаб диаграммы' })
      await expect(page.locator('.diagram-edge-label--port').first()).toBeVisible()

      for (let i = 0; i < 6 && (await canvasScale(page)) >= 0.6; i++) {
        await controls.getByRole('button', { name: 'Уменьшить масштаб' }).click()
        await page.waitForTimeout(250)
      }
      expect(await canvasScale(page)).toBeLessThan(0.6)
      await expect(page.locator('.diagram-edge-label--port').first()).toBeHidden()

      await controls.getByRole('button', { name: 'Показать всю диаграмму' }).click()
      await expect(page.locator('.diagram-edge-label--port').first()).toBeVisible()
    })
  })
}
