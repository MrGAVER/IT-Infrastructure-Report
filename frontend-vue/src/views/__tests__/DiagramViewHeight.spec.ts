import { describe, expect, it } from 'vitest'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'

// UI-05 (ревью 2.158.0): высота экрана диаграммы считается от фактической шапки и dvh, а холст имеет нижний предел.
describe('UI-05: DiagramView — высота', () => {
  const css = readStyles('src/views/DiagramView.vue')
  const view = ruleBody(css, '.diagram-view')!

  it('высота: окно минус шапка и отступы контента через dvh, а не 100vh − 96px', () => {
    expect(view).not.toContain('96px')
    const heights = [...view.matchAll(/height:\s*([^;]+);/g)].map((m) => m[1].trim())
    // Запасное объявление для браузеров без dvh идёт первым, dvh — последним (побеждает там, где поддерживается).
    expect(heights[0]).toContain('100vh')
    expect(heights[heights.length - 1]).toBe('calc(100dvh - var(--topbar-h, 68px) - var(--content-pad-top, 18px) - var(--content-pad-bottom, 32px))')
  })

  it('холст не сжимается ниже 320 px и занимает остаток высоты', () => {
    const canvas = ruleBody(css, '.canvas-wrap')
    expect(declaration(canvas, 'min-height')).toBe('320px')
    expect(declaration(canvas, 'flex')).toBe('1 1 auto')
  })
})
