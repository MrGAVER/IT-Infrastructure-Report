import { describe, it, expect } from 'vitest'
import { DEFAULT_FLOATING_PANEL_OPTIONS, floatingPanelLayout } from '../floatingPanel'

const VIEWPORT = 800
const field = (top: number, bottom = top + 30) => ({ top, bottom, left: 40, width: 200 })

describe('floatingPanelLayout', () => {
  it('места снизу достаточно: панель открывается вниз, под полем с зазором', () => {
    const { openUp, style } = floatingPanelLayout(field(100), VIEWPORT)

    expect(openUp).toBe(false)
    expect(style).toEqual({ left: '40px', width: '200px', maxHeight: '240px', top: '134px' })
    expect(style.bottom).toBeUndefined()
  })

  it('снизу тесно, сверху просторно: панель открывается вверх и привязана к нижнему краю', () => {
    const { openUp, style } = floatingPanelLayout(field(700), VIEWPORT)

    expect(openUp).toBe(true)
    expect(style.bottom).toBe(`${VIEWPORT - 700 + DEFAULT_FLOATING_PANEL_OPTIONS.gap}px`)
    expect(style.top).toBeUndefined()
    expect(style.maxHeight).toBe('240px')
  })

  it('высота ограничивается свободным местом, но не меньше минимальной', () => {
    // Снизу 100px: 800 - 670 - 8 - 4 = 118, сверху места ещё меньше — остаётся вниз с урезанной высотой.
    expect(floatingPanelLayout({ top: 5, bottom: 670, left: 0, width: 100 }, VIEWPORT).style.maxHeight).toBe('118px')
    // Тесно с обеих сторон: высота не схлопывается ниже minHeight.
    const tiny = floatingPanelLayout({ top: 40, bottom: 70, left: 0, width: 100 }, 120)
    expect(tiny.style.maxHeight).toBe(`${DEFAULT_FLOATING_PANEL_OPTIONS.minHeight}px`)
  })

  it('при равном дефиците места остаётся вниз (вверх — только если сверху строго больше)', () => {
    // Поле по центру короткого окна: снизу и сверху поровну.
    const { openUp } = floatingPanelLayout({ top: 85, bottom: 115, left: 0, width: 100 }, 200)
    expect(openUp).toBe(false)
  })

  it('координаты округляются до целых пикселей', () => {
    const { style } = floatingPanelLayout({ top: 100.4, bottom: 130.6, left: 40.5, width: 199.7 }, VIEWPORT)
    expect(style).toMatchObject({ left: '41px', width: '200px', top: '135px' })
  })
})
