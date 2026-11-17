// Поиск по тексту для клиентских списков («Другие справочники», «Стеки устройств»): запрос делится на слова, запись
// подходит, если КАЖДОЕ слово встречается хотя бы в одном из её текстов. Регистр и «ё»/«е» не различаются — «ядр» находит
// «Ядро», «берёзка» — «Березка». Так запрос из двух слов («cisco ядр») сужает выбор, а не расширяет его.

/** Приведение к виду для сравнения: нижний регистр, «ё» → «е», без пробелов по краям. */
export function normalizeSearchText(value: string): string {
  return value.toLowerCase().replaceAll('ё', 'е').trim()
}

/** Слова запроса в нормализованном виде; пустой или состоящий из пробелов запрос — пустой массив (фильтра нет). */
export function searchTokens(query: string): string[] {
  const normalized = normalizeSearchText(query)
  return normalized ? normalized.split(/\s+/) : []
}

/**
 * Подходит ли запись под запрос: каждое слово запроса — подстрока хотя бы одного из текстов.
 * Пустые значения (null/undefined/'') игнорируются. Без слов в запросе подходит любая запись.
 */
export function matchesSearchTokens(tokens: readonly string[], texts: readonly (string | null | undefined)[]): boolean {
  if (!tokens.length) return true
  const haystack = texts
    .filter((t): t is string => typeof t === 'string' && t !== '')
    .map(normalizeSearchText)
  return tokens.every((token) => haystack.some((text) => text.includes(token)))
}

/** Записи, подходящие под запрос; пустой запрос возвращает исходный массив без копирования. */
export function filterBySearch<T>(items: readonly T[], query: string, textsOf: (item: T) => readonly (string | null | undefined)[]): readonly T[] {
  const tokens = searchTokens(query)
  if (!tokens.length) return items
  return items.filter((item) => matchesSearchTokens(tokens, textsOf(item)))
}
