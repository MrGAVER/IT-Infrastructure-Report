import { describe, expect, it } from 'vitest'
import { FIT_VIEW_OPTIONS, resolveInitialView } from '../diagramViewport'

describe('UI-01: resolveInitialView — приоритет начального вида холста', () => {
  it('без сохранённого вида граф вписывается в холст', () => {
    expect(resolveInitialView(null)).toEqual({ kind: 'fit' })
    expect(resolveInitialView(undefined)).toEqual({ kind: 'fit' })
  })

  it('сохранённый вид пользователя выигрывает у вписывания и переводится в формат Vue Flow', () => {
    expect(resolveInitialView({ zoom: 0.5, pan_x: 120, pan_y: -40 })).toEqual({ kind: 'restore', viewport: { x: 120, y: -40, zoom: 0.5 } })
  })

  it('вид по умолчанию (0, 0, 1) считается «не сохранённым»: его восстановление оставило бы граф обрезанным', () => {
    expect(resolveInitialView({ zoom: 1, pan_x: 0, pan_y: 0 })).toEqual({ kind: 'fit' })
  })

  it('повреждённые значения не доходят до холста: нулевой, отрицательный и нечисловой масштаб, NaN в панораме', () => {
    for (const bad of [
      { zoom: 0, pan_x: 5, pan_y: 5 },
      { zoom: -2, pan_x: 5, pan_y: 5 },
      { zoom: Number.NaN, pan_x: 5, pan_y: 5 },
      { zoom: 1, pan_x: Number.POSITIVE_INFINITY, pan_y: 5 },
      { zoom: 1, pan_x: 5, pan_y: Number.NaN },
    ]) {
      expect(resolveInitialView(bad)).toEqual({ kind: 'fit' })
    }
  })

  it('поля вписывания заданы, а масштаб ограничен единицей', () => {
    expect(FIT_VIEW_OPTIONS).toEqual({ padding: 0.1, maxZoom: 1 })
  })
})
