import { expect, test, type Page } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { cleanupSeeded, seedTopology } from './seed.ts'

// F-07 (код-ревью main): рёбра диаграммы не должны проходить сквозь чужие узлы и ложиться друг на друга. Раньше ребро было кривой Безье между
// засечками у нижнего края узлов: связи внутри ряда сетки сливались в одну горизонталь вдоль границы узлов, связи между рядами шли по
// диагонали через узлы (на схеме из 18 узлов — 16 из 22 рёбер). Проверка идёт по настоящей геометрии в браузере: точки каждой линии
// берутся из SVG-пути, узлы — из их прямоугольников на странице.

test.afterEach(async ({ request }) => {
  await cleanupSeeded(request)
})

interface EdgeGeometry {
  edges: number
  nodes: number
  /** Рёбра, у которых хотя бы одна точка лежит внутри чужого узла (с отступом 4 px от границы). */
  throughNodes: number
  /** Пары рёбер, лежащие на одной линии больше 40 px. */
  overlappingPairs: number
}

async function measureEdges(page: Page): Promise<EdgeGeometry> {
  return page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('.vue-flow__node')).map((el) => el.getBoundingClientRect())
    const paths = Array.from(document.querySelectorAll('.vue-flow__edge path.vue-flow__edge-path'))
    const STEP = 3
    const samples = paths.map((path) => {
      const svg = path as SVGPathElement
      const matrix = svg.getScreenCTM()!
      const points: Array<{ x: number; y: number }> = []
      for (let at = 0; at <= svg.getTotalLength(); at += STEP) {
        const p = svg.getPointAtLength(at)
        points.push({ x: matrix.a * p.x + matrix.c * p.y + matrix.e, y: matrix.b * p.x + matrix.d * p.y + matrix.f })
      }
      return points
    })
    // Масштаб холста: пороги в px канваса пересчитываются в px экрана.
    const scale = new DOMMatrix(getComputedStyle(document.querySelector('.vue-flow__transformationpane')!).transform).a
    const inset = 4 * scale
    const throughNodes = samples.filter((points) =>
      points.some((p) => nodes.some((n) => p.x > n.left + inset && p.x < n.right - inset && p.y > n.top + inset && p.y < n.bottom - inset)),
    ).length
    const cell = Math.max(1, 1.5 * scale)
    const keys = samples.map((points) => new Set(points.map((p) => `${Math.round(p.x / cell)}:${Math.round(p.y / cell)}`)))
    const minShared = Math.ceil(40 / STEP) // 40 px канваса: отсчёты берутся через STEP единиц пути, то есть в масштабе канваса
    let overlappingPairs = 0
    for (let i = 0; i < keys.length; i++) {
      for (let j = i + 1; j < keys.length; j++) {
        let shared = 0
        for (const key of keys[i]) if (keys[j].has(key)) shared++
        if (shared >= minShared) overlappingPairs++
      }
    }
    return { edges: paths.length, nodes: nodes.length, throughNodes, overlappingPairs }
  })
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test.describe(`рёбра диаграммы ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport })

    test('F-07: на схеме из 18 узлов рёбра не проходят сквозь узлы и не накладываются друг на друга', async ({ page, request }) => {
      const { diagramId, links } = await seedTopology(request)
      expect(links).toBeGreaterThanOrEqual(20)
      await openApp(page, `/diagrams/${diagramId}`)
      await page.locator('.vue-flow__node').first().waitFor()
      await expect.poll(async () => (await measureEdges(page)).edges, { message: 'рёбра не отрисованы' }).toBe(links)
      // Маршруты считаются после измерения узлов: ждём, пока линии перестанут проходить сквозь узлы, а не фиксируем первый кадр.
      await expect.poll(async () => (await measureEdges(page)).throughNodes, { message: 'рёбра проходят сквозь узлы', timeout: 10_000 }).toBe(0)
      const geometry = await measureEdges(page)
      expect(geometry.nodes).toBeGreaterThanOrEqual(15)
      expect(geometry.overlappingPairs, 'рёбра лежат друг на друге').toBe(0)
    })
  })
}

test.describe('рёбра диаграммы после перетаскивания узла', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('F-07: после сдвига узла маршруты пересчитываются и снова обходят узлы', async ({ page, request }) => {
    const { diagramId, links } = await seedTopology(request)
    await openApp(page, `/diagrams/${diagramId}`)
    await page.locator('.vue-flow__node').first().waitFor()
    await expect.poll(async () => (await measureEdges(page)).edges).toBe(links)
    await expect.poll(async () => (await measureEdges(page)).throughNodes, { timeout: 10_000 }).toBe(0)

    // Узел из верхнего ряда переносим в свободное место ниже схемы — линии, шедшие к нему, должны перестроиться вокруг остальных узлов.
    // Схема вписана в холст по высоте, поэтому свободное место появляется только после уменьшения масштаба; его положение берём
    // из измеренных прямоугольников узлов, а не из размеров холста, иначе узел мог упасть на другой узел и «сквозь узлы» стало бы
    // неизбежным.
    for (let i = 0; i < 2; i++) await page.getByRole('button', { name: 'Уменьшить масштаб' }).click()
    const node = page.locator('.vue-flow__node').first()
    await expect
      .poll(
        async () => {
          const rects = await page.locator('.vue-flow__node').evaluateAll((els) => els.map((el) => el.getBoundingClientRect().bottom))
          const canvasBox = (await page.locator('.canvas-wrap').boundingBox())!
          return canvasBox.y + canvasBox.height - Math.max(...rects)
        },
        { message: 'под схемой нет свободного места для переноса узла' },
      )
      .toBeGreaterThan(120)
    const box = (await node.boundingBox())!
    const lowest = await page.locator('.vue-flow__node').evaluateAll((els) => Math.max(...els.map((el) => el.getBoundingClientRect().bottom)))
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, lowest + box.height + 30, { steps: 12 })
    await page.mouse.up()

    await expect.poll(async () => (await measureEdges(page)).throughNodes, { message: 'после сдвига узла рёбра проходят сквозь узлы', timeout: 10_000 }).toBe(0)
    expect((await measureEdges(page)).edges).toBe(links)
  })
})
