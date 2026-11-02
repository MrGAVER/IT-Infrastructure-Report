import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * Помощники для регрессионных тестов вёрстки, которую jsdom не считает.
 *
 * vitest.config.ts выставляет `css: false` — стили компонентов в тестах пустые, а jsdom не делает раскладку.
 * Поэтому дефекты вида «у .sidebar нет overflow-y» проверяются по исходнику стилей, а их поведение —
 * ручной проверкой в браузере (см. раздел «Ручные критерии приёмки» в ревью). process.cwd() — корень
 * frontend-vue: vitest всегда запускается оттуда.
 */
export function readSource(relativePath: string): string {
  return readFileSync(path.resolve(process.cwd(), relativePath), 'utf-8')
}

/** Содержимое всех блоков `<style>` однофайлового компонента (для .css-файла — весь файл). */
export function readStyles(relativePath: string): string {
  const source = readSource(relativePath)
  if (!relativePath.endsWith('.vue')) return source
  return [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((match) => match[1]).join('\n')
}

/** Тело первого блока `@media <query> { … }` (с учётом вложенных скобок) или null, если такого блока нет. */
export function mediaBlock(css: string, query: string): string | null {
  const start = css.indexOf(`@media ${query}`)
  if (start === -1) return null
  const open = css.indexOf('{', start)
  let depth = 0
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++
    else if (css[i] === '}' && --depth === 0) return css.slice(open + 1, i)
  }
  return null
}

/** Объявления правила с точно таким селектором (`.sidebar`, `.sidebar:not(.open)`) или null. */
export function ruleBody(css: string, selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(?:^|[}\\s])${escaped}\\s*{([^}]*)}`).exec(css)
  return match ? match[1] : null
}

/** Объявление свойства из тела правила: значение без пробелов по краям или null. */
export function declaration(body: string | null, property: string): string | null {
  if (body === null) return null
  const match = new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*([^;]+);?`).exec(body)
  return match ? match[1].trim() : null
}
