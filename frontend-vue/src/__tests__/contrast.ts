// Контраст по WCAG 2.x для тестов токенов темы: тема тёмная, и «на глаз» пары вроде красного на тёмно-красном выглядят нормально,
// а расчёт даёт 3,96 : 1 при нужных 4,5.

function channel(value: number): number {
  const v = value / 255
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) throw new Error(`ожидался цвет #rrggbb, получено «${hex}»`)
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16))
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** Отношение контрастности двух цветов #rrggbb: от 1 (одинаковые) до 21. */
export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

/** Значение пользовательского свойства из тела правила `selector { … }` файла стилей, либо null. */
export function tokenValue(css: string, selector: string, token: string): string | null {
  const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const rule = new RegExp(`(?:^|[}\\s,])${escape(selector)}\\s*(?:,[^{]*)?{([^}]*)}`, 'g')
  for (const match of css.matchAll(rule)) {
    const declaration = new RegExp(`${escape(token)}\\s*:\\s*([^;]+);`).exec(match[1])
    if (declaration) return declaration[1].trim()
  }
  return null
}
