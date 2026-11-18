// Русское склонение существительного по числу: 1 устройство, 2 устройства, 5 устройств, 11 устройств, 21 устройство.

/** Форма слова для числа n: [для 1, для 2–4, для 5–20 и 0]; 11–14 всегда «много», как и 111–114. */
export function pluralRu(n: number, forms: readonly [one: string, few: string, many: string]): string {
  const abs = Math.abs(Math.trunc(n))
  const mod10 = abs % 10
  const mod100 = abs % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return forms[1]
  return forms[2]
}

/** «N устройство/устройства/устройств» — счётчик в строке стека. */
export function deviceCountLabel(n: number): string {
  return `${n} ${pluralRu(n, ['устройство', 'устройства', 'устройств'])}`
}
