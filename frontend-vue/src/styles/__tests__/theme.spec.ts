import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { readStyles } from '../../__tests__/cssSource'
import { contrast, tokenValue } from '../../__tests__/contrast'

// vitest.config.ts выставляет css: false — модули стилей (в т.ч. с ?raw) стабятся пустой
// строкой, поэтому содержимое читаем напрямую с диска. process.cwd() — корень frontend-vue
// (vitest всегда запускается оттуда, см. package.json "test": "vitest run").
const themeCssPath = path.resolve(process.cwd(), 'src/styles/theme.css')
const themeCss = readFileSync(themeCssPath, 'utf-8')

describe('theme.css', () => {
  // Регрессия: var(--surface-1) используется в HelpTip.vue и DeviceInterfacesEditor.vue без
  // CSS-фолбэка, но переменная нигде не была объявлена в :root — background становился
  // невалидным. Видимо это выглядело как прозрачная подложка попапа "?" у "Шаблон имени"
  // (п.1.3.2) и белый фон нативного выпадающего списка "VLAN порта" в режиме Access (п.1.3.10) —
  // в обоих браузер не мог посчитать background: var(--surface-1) и подставлял свой дефолт.
  it('defines --surface-1 in :root so var(--surface-1) without a CSS fallback stays valid', () => {
    expect(themeCss).toMatch(/:root\s*{[^}]*--surface-1\s*:/s)
  })

  // UI-8 (ревью merge/review-2158-executors): color-scheme: dark стоял только у одного input[type=date] в DeviceMainFields.vue, поэтому
  // чекбоксы оставались белыми, нативный select — светлым, а полосы прокрутки — светлыми поверх тёмной темы. Объявление живёт в одном месте.
  it('UI-8: объявляет color-scheme: dark в :root — нативные контролы и полосы прокрутки тёмные везде', () => {
    expect(themeCss).toMatch(/:root\s*{[^}]*color-scheme\s*:\s*dark\s*;/s)
  })

  it('UI-8: локальных color-scheme в компонентах не осталось (единственный источник — theme.css)', () => {
    expect(readStyles('src/components/DeviceMainFields.vue')).not.toMatch(/color-scheme\s*:/)
  })

  // UI-9: шрифты подключаются локально (пакеты @fontsource-variable, см. base.css) — их семейства называются «<Имя> Variable».
  it('UI-9: стеки шрифтов начинаются с локально подключённых семейств', () => {
    expect(themeCss).toMatch(/--font-display\s*:\s*'Golos Text Variable'/)
    expect(themeCss).toMatch(/--font-body\s*:\s*'Inter Variable'/)
    expect(themeCss).toMatch(/--font-mono\s*:\s*'JetBrains Mono Variable'/)
  })
})

// UI-07 (ревью 2.158.0): три пары токенов не проходили WCAG AA. Значения считаются, а не «на глаз».
describe('UI-07: контраст токенов темы', () => {
  // Значение токена схемы: сначала в правиле самой схемы, затем в :root; алиасы вида var(--brand) разворачиваются до цвета.
  const token = (selector: string, name: string): string => {
    const value = tokenValue(themeCss, selector, name) ?? tokenValue(themeCss, ':root', name)
    if (value === null) throw new Error(`в theme.css нет ${name} в ${selector}`)
    const alias = /^var\((--[\w-]+)\)$/.exec(value)
    return alias ? token(selector, alias[1]) : value
  }
  const SCHEMES = [
    { name: 'teal', selector: ':root' },
    { name: 'indigo', selector: "[data-scheme='indigo']" },
    { name: 'copper', selector: "[data-scheme='copper']" },
  ]

  it('текст «тревога» на --status-crit-soft: --crit-ink даёт ≥ 4,5 : 1 (сам --status-crit — 3,96)', () => {
    expect(contrast(token(':root', '--status-crit'), token(':root', '--status-crit-soft'))).toBeLessThan(4.5)
    expect(contrast(token(':root', '--crit-ink'), token(':root', '--status-crit-soft'))).toBeGreaterThanOrEqual(4.5)
  })

  it.each(SCHEMES)('схема $name: текст --brand-ink на --brand-soft ≥ 4,5 : 1 (активный пункт меню, 12,8 px)', ({ selector }) => {
    expect(contrast(token(selector, '--brand-ink'), token(selector, '--brand-soft'))).toBeGreaterThanOrEqual(4.5)
  })

  it('«Индиго» без --brand-ink не проходит — токен действительно нужен, а не придуман', () => {
    expect(contrast(token("[data-scheme='indigo']", '--brand'), token("[data-scheme='indigo']", '--brand-soft'))).toBeLessThan(4.5)
  })

  it.each(SCHEMES)('схема $name: граница поля --field-border ≥ 3 : 1 на --surface и на --bg (WCAG 1.4.11)', ({ selector }) => {
    const border = token(selector, '--field-border')
    expect(contrast(border, token(selector, '--surface'))).toBeGreaterThanOrEqual(3)
    expect(contrast(border, token(selector, '--bg'))).toBeGreaterThanOrEqual(3)
  })

  it('--ink-muted читается на новой поверхности --surface-3 (счётчик в справочниках)', () => {
    expect(contrast(token(':root', '--ink-muted'), token(':root', '--surface-3'))).toBeGreaterThanOrEqual(4.5)
  })
})

// Охранный тест: пара «текст --status-crit / --brand на своей мягкой подложке» не возвращается ни в один файл.
// После слияния потоков исключений нет: файлы второго исполнителя переведены на --crit-ink / --brand-ink.
describe('UI-07: текст на мягкой подложке использует --crit-ink / --brand-ink', () => {
  const SRC = path.resolve(process.cwd(), 'src')

  function styled(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) return entry.name === '__tests__' ? [] : styled(full)
      return /\.(vue|css)$/.test(entry.name) ? [full] : []
    })
  }

  const offenders = (kind: 'crit' | 'brand'): string[] =>
    styled(SRC)
      .map((file) => path.relative(SRC, file).split(path.sep).join('/'))
      .filter((file) => file !== 'styles/theme.css')
      .filter((file) => {
        const text = readFileSync(path.join(SRC, file), 'utf-8')
        const background = kind === 'crit' ? /background(?:-color)?:\s*var\(--status-crit-soft[,)]/ : /background(?:-color)?:\s*var\(--brand-soft[,)]/
        const color = kind === 'crit' ? /(?<![\w-])color:\s*var\(--status-crit\)/ : /(?<![\w-])color:\s*var\(--brand\)/
        return [...text.matchAll(/\{([^{}]*)\}/g)].some((block) => background.test(block[1]) && color.test(block[1]))
      })

  it('красный текст на --status-crit-soft — только через --crit-ink', () => {
    expect(offenders('crit')).toEqual([])
  })

  it('текст акцента на --brand-soft — только через --brand-ink (иначе «Индиго» не проходит контраст)', () => {
    expect(offenders('brand')).toEqual([])
  })
})

// UI-08: --border-muted, --surface-hover, --surface-3, --shadow-s и --shadow-m использовались нигде не объявленными, а запасные значения
// (белый фон, rgba(0,0,0,0.12)) рассчитаны на светлую тему — на тёмной hover и рамка почти невидимы.
describe('UI-08: каждый var(--x) имеет объявление', () => {
  const SRC = path.resolve(process.cwd(), 'src')

  function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(full)
      return /\.(vue|css|ts)$/.test(entry.name) && !entry.name.includes('.spec.') ? [full] : []
    })
  }

  const files = sourceFiles(SRC).map((file) => ({ file: path.relative(SRC, file), text: readFileSync(file, 'utf-8') }))
  const declared = new Set<string>()
  const used = new Map<string, Set<string>>()
  for (const { file, text } of files) {
    // Объявления в CSS (`--x: …`) и из JS: style.setProperty('--x', …), :style="{ '--x': … }".
    for (const m of text.matchAll(/(--[\w-]+)\s*:/g)) declared.add(m[1])
    for (const m of text.matchAll(/['"`](--[\w-]+)['"`]/g)) declared.add(m[1])
    for (const m of text.matchAll(/var\((--[\w-]+)/g)) used.set(m[1], (used.get(m[1]) ?? new Set()).add(file))
  }

  it('нет ни одного var(--x) на необъявленный токен', () => {
    const undeclared = [...used.keys()].filter((name) => !declared.has(name)).map((name) => `${name} ← ${[...used.get(name)!].join(', ')}`)
    expect(undeclared).toEqual([])
  })

  it('токены из ревью объявлены именно в theme.css', () => {
    for (const name of ['--border-muted', '--surface-hover', '--surface-3', '--shadow-s', '--shadow-m', '--crit-ink', '--brand-ink', '--field-border']) {
      expect(themeCss, name).toMatch(new RegExp(`${name}\\s*:`))
    }
  })

  it('у объявленных в theme.css токенов в местах использования нет светлых запасных значений', () => {
    for (const name of ['--border-muted', '--surface-hover', '--surface-3', '--shadow-s', '--shadow-m']) {
      const withFallback = files.filter(({ text }) => new RegExp(`var\\(${name}\\s*,`).test(text)).map(({ file }) => file)
      expect(withFallback, `${name}: запасное значение осталось в`).toEqual([])
    }
  })
})
