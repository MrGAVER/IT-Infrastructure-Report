// Окно номеров страниц для пейджера: при тысячах записей нельзя рисовать кнопку на каждую
// страницу. Всегда показываются первая, последняя и соседи текущей; пропуски — '…'.
export type PagerItem = number | '…'

export function pagerItems(current: number, pageCount: number, neighbours = 1): PagerItem[] {
  if (pageCount <= 0) return []
  const wanted = new Set<number>([1, pageCount])
  for (let p = current - neighbours; p <= current + neighbours; p++) {
    if (p >= 1 && p <= pageCount) wanted.add(p)
  }
  const sorted = [...wanted].sort((a, b) => a - b)
  const items: PagerItem[] = []
  sorted.forEach((page, i) => {
    const previous = sorted[i - 1]
    if (previous !== undefined && page - previous > 1) {
      // Пропуск в одну страницу проще показать самой страницей, чем многоточием.
      if (page - previous === 2) items.push(previous + 1)
      else items.push('…')
    }
    items.push(page)
  })
  return items
}
