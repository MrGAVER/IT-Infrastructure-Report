import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// UI-2 (ревью merge/review-2158-executors): `i-download` использовалась в ReportsView и ReportTemplatesView, но в
// public/icons.svg её не было — браузер молча рисует пустой <use>, и кнопки «Сформировать и скачать» показывали пустой
// квадрат 16×16. Ни vue-tsc, ни jsdom такое не видят, поэтому спрайт сверяется с исходниками отдельным тестом.
const SRC_DIR = path.resolve(process.cwd(), 'src')
const SPRITE_PATH = path.resolve(process.cwd(), 'public/icons.svg')

/** Все .vue и .ts под src, кроме тестов (__tests__) и файлов *.spec.ts / *.test.ts. */
function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) return name === '__tests__' ? [] : collectSourceFiles(full)
    return /\.(vue|ts)$/.test(name) && !/\.(spec|test)\.ts$/.test(name) ? [full] : []
  })
}

const sprite = readFileSync(SPRITE_PATH, 'utf-8')
const definedIds = [...sprite.matchAll(/<symbol\b[^>]*\bid="([^"]+)"/g)].map((match) => match[1])

// Два вида ссылок: `/icons.svg#i-name` в шаблонах и целые строковые литералы 'i-name' (массивы primaryNav/catalogNav/systemNav
// в Sidebar.vue, из которых имя подставляется в <use> динамически). Требование «строка целиком в кавычках» отсекает
// посторонние совпадения вроде `multi-select` или `ui-monospace`.
const ICON_REFERENCE = /(?:icons\.svg#|['"`])(i-[a-z][a-z0-9-]*)(?=['"`])/g

function collectUsedIcons(): Map<string, string[]> {
  const used = new Map<string, string[]>()
  for (const file of collectSourceFiles(SRC_DIR)) {
    const text = readFileSync(file, 'utf-8')
    for (const match of text.matchAll(ICON_REFERENCE)) {
      const files = used.get(match[1]) ?? []
      if (!files.includes(path.relative(SRC_DIR, file))) files.push(path.relative(SRC_DIR, file))
      used.set(match[1], files)
    }
  }
  return used
}

describe('public/icons.svg', () => {
  it('содержит каждую иконку, на которую ссылается код (i-… в <use> и в массивах меню)', () => {
    const used = collectUsedIcons()
    // Защита от тихого прохождения: если разбор ссылок сломается, used опустеет и «нет пропусков» станет ложью.
    expect(used.size).toBeGreaterThan(20)

    const defined = new Set(definedIds)
    const missing = [...used.entries()].filter(([id]) => !defined.has(id)).map(([id, files]) => `${id} ← ${files.join(', ')}`)
    expect(missing).toEqual([])
  })

  it('не содержит двух символов с одним id (браузер берёт первый, второй молча теряется)', () => {
    expect(definedIds.filter((id, index) => definedIds.indexOf(id) !== index)).toEqual([])
  })

  it('все символы описаны в одной системе: 24×24, штрих по цвету текста', () => {
    const symbols = [...sprite.matchAll(/<symbol\b[^>]*>/g)].map((match) => match[0])
    expect(symbols.length).toBe(definedIds.length)
    for (const tag of symbols) {
      expect(tag).toContain('viewBox="0 0 24 24"')
      expect(tag).toContain('stroke="currentColor"')
    }
  })
})

describe('UI-20: иконка «здание»', () => {
  const sprite = readFileSync(path.resolve(process.cwd(), 'public/icons.svg'), 'utf-8')
  const symbol = (id: string) => new RegExp(`<symbol id="${id}"[^>]*>([\\s\\S]*?)</symbol>`).exec(sprite)?.[1] ?? ''

  it('i-building больше не лист документа: прежний прямоугольник 14×18 с рядами «строк» удалён', () => {
    expect(symbol('i-building')).not.toContain('<rect x="5" y="3" width="14" height="18"')
  })

  it('силуэт здания: земля, башня с окнами, пристройка и дверь', () => {
    const building = symbol('i-building')
    expect(building).toContain('d="M3 21h18"') // линия земли — у документа её нет
    expect(building.match(/<path\b/g)!.length).toBeGreaterThanOrEqual(4)
  })

  it('иконка документа i-file не изменилась — по ней «Отчёты» отличаются от «Зданий»', () => {
    expect(symbol('i-file')).toContain('M7 3h7l4 4v14H7z')
  })
})
