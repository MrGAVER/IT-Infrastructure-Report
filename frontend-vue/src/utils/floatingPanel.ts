// Расчёт положения «плавающей» панели выпадающего списка (SearchableSelect в режиме floating).
//
// Панель выводится в <body> с position: fixed, чтобы её не обрезали прокручиваемые предки (таблица с overflow-x: auto,
// тело модалки): у overflow-контейнера вторая ось тоже становится auto, и абсолютно позиционированный список уходил под
// край блока — его приходилось прокручивать. Координаты считаются от поля ввода (anchor) в координатах окна браузера.
// Функция чистая — только числа на входе и стили на выходе, DOM не трогает, поэтому проверяется без монтирования компонента.

/** Прямоугольник поля ввода в координатах окна (подмножество DOMRect: достаточно для расчёта). */
export interface AnchorRect {
  top: number
  bottom: number
  left: number
  width: number
}

export interface FloatingPanelOptions {
  /** Предельная высота панели, px (как у обычного списка). */
  maxHeight: number
  /** Минимальная высота: если места мало с обеих сторон, панель не схлопывается до нескольких пикселей. */
  minHeight: number
  /** Зазор между полем и панелью, px. */
  gap: number
  /** Отступ от края окна, px: панель не прижимается к самому краю экрана. */
  viewportMargin: number
}

export interface FloatingPanelLayout {
  /** Панель открывается вверх от поля (снизу не хватило места, а сверху его больше). */
  openUp: boolean
  /** Инлайн-стили панели: left/width/maxHeight и одно из top / bottom. */
  style: Record<string, string>
}

export const DEFAULT_FLOATING_PANEL_OPTIONS: FloatingPanelOptions = {
  maxHeight: 240,
  minHeight: 96,
  gap: 4,
  viewportMargin: 8,
}

/**
 * Куда поставить панель списка относительно поля ввода.
 *
 * По умолчанию панель открывается вниз. Если под полем меньше места, чем нужно для полной высоты, а над полем его больше,
 * панель открывается вверх. Высота ограничивается свободным местом с выбранной стороны (внутри — прокрутка списка), но не
 * меньше `minHeight`.
 *
 * @example
 * floatingPanelLayout({ top: 100, bottom: 130, left: 40, width: 200 }, 800).style
 * // { left: '40px', width: '200px', maxHeight: '240px', top: '134px' }
 */
export function floatingPanelLayout(
  anchor: AnchorRect,
  viewportHeight: number,
  options: FloatingPanelOptions = DEFAULT_FLOATING_PANEL_OPTIONS,
): FloatingPanelLayout {
  const { maxHeight, minHeight, gap, viewportMargin } = options
  const spaceBelow = viewportHeight - anchor.bottom - viewportMargin - gap
  const spaceAbove = anchor.top - viewportMargin - gap

  const openUp = spaceBelow < maxHeight && spaceAbove > spaceBelow
  const available = openUp ? spaceAbove : spaceBelow
  const height = Math.round(Math.min(maxHeight, Math.max(minHeight, available)))

  const style: Record<string, string> = {
    left: `${Math.round(anchor.left)}px`,
    width: `${Math.round(anchor.width)}px`,
    maxHeight: `${height}px`,
  }
  if (openUp) style.bottom = `${Math.round(viewportHeight - anchor.top + gap)}px`
  else style.top = `${Math.round(anchor.bottom + gap)}px`

  return { openUp, style }
}
