// Начальный вид холста диаграммы (UI-01, ревью 2.158.0): вписать граф в окно или вернуть сохранённые панораму и масштаб.
// Выбор вынесен в чистую функцию, чтобы приоритет был определён в одном месте и проверялся без подъёма <VueFlow>.
import type { DiagramViewport } from '../api/diagrams'

/** Параметры fitView: поля 10 % по краям, масштаб не больше 1 — маленький граф не раздувается на весь холст. */
export const FIT_VIEW_OPTIONS = { padding: 0.1, maxZoom: 1 } as const

/** Вид в формате Vue Flow (в API панорама лежит в pan_x/pan_y). */
export interface FlowViewport {
  x: number
  y: number
  zoom: number
}

export type InitialView = { kind: 'restore'; viewport: FlowViewport } | { kind: 'fit' }

/**
 * Приоритет такой: сохранённый вид пользователя выигрывает, иначе граф вписывается в холст.
 * «Нет сохранённого вида» — это и null, и повреждённые значения, и ровно вид по умолчанию (0, 0, масштаб 1): он неотличим от
 * «холст не трогали», а восстановление его оставило бы граф обрезанным, как раньше. Интерфейс сам вид на сервер пока не
 * отправляет, поэтому сохранённый вид бывает только у диаграмм, записанных через API.
 */
export function resolveInitialView(saved: DiagramViewport | null | undefined): InitialView {
  if (!saved) return { kind: 'fit' }
  const { zoom, pan_x: x, pan_y: y } = saved
  if (![zoom, x, y].every(Number.isFinite) || zoom <= 0) return { kind: 'fit' }
  if (x === 0 && y === 0 && zoom === 1) return { kind: 'fit' }
  return { kind: 'restore', viewport: { x, y, zoom } }
}
