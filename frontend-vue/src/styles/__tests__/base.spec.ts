import { describe, expect, it } from 'vitest'
import { declaration, readSource, readStyles, ruleBody } from '../../__tests__/cssSource'

const baseCss = readStyles('src/styles/base.css')

describe('base.css — .status-dot (UI-6)', () => {
  // UI-6 (ревью merge/review-2158-executors): box-shadow 0 0 0 3px currentColor при opacity .85 давал сплошной круг 12 px вместо
  // точки 6 px с ореолом (особенно заметно у «Нет» в колонке SIEM).
  const body = ruleBody(baseCss, '.status-dot')

  it('ореол — полупрозрачный оттенок цвета точки, а не тот же сплошной цвет', () => {
    expect(declaration(body, 'box-shadow')).toBe('0 0 0 3px color-mix(in srgb, currentColor 25%, transparent)')
  })

  it('сама точка не полупрозрачная (opacity: 1), размер остаётся 6 px', () => {
    expect(declaration(body, 'opacity')).toBe('1')
    expect(declaration(body, 'width')).toBe('6px')
    expect(declaration(body, 'height')).toBe('6px')
  })
})

describe('шрифты — локальные, без внешнего CDN (UI-9)', () => {
  // UI-9: @import с fonts.googleapis.com — внешний запрос при каждом открытии приложения в закрытом контуре: блокирует отрисовку,
  // выдаёт факт использования и IP клиента. К тому же серверный CSP (style-src 'self') такой импорт всё равно блокирует.
  it('base.css, theme.css и index.html не обращаются к внешним хостам шрифтов (комментарии не в счёт)', () => {
    const withoutComments = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '')
    for (const text of [baseCss, readSource('index.html'), readStyles('src/styles/theme.css')]) {
      expect(withoutComments(text)).not.toMatch(/googleapis|gstatic|https?:\/\/[^\s'")]*font/i)
    }
  })

  it('base.css подключает Inter, Golos Text и JetBrains Mono из установленных пакетов @fontsource-variable', () => {
    for (const family of ['inter', 'golos-text', 'jetbrains-mono']) {
      expect(baseCss).toContain(`@import '@fontsource-variable/${family}/wght.css';`)
    }
  })

  it('пакеты шрифтов объявлены в зависимостях (иначе @import не соберётся на чистой установке)', () => {
    const dependencies = JSON.parse(readSource('package.json')).dependencies as Record<string, string>
    for (const family of ['inter', 'golos-text', 'jetbrains-mono']) {
      expect(dependencies).toHaveProperty(`@fontsource-variable/${family}`)
    }
  })
})

// UI-07: граница полей — --field-border; правило одно, вместо 64 scoped-правил в 48 файлах.
describe('base.css — граница полей ввода (UI-07)', () => {
  const css = readStyles('src/styles/base.css')

  it('поля .field, строк таблиц и фильтров получают border-color: var(--field-border), кроме состояния :focus', () => {
    expect(css).toMatch(/html :is\(\.field, \.nested-row, \.ip-row, \.filter-row, \.ss-input-row\)\s*:is\(input:not\(\[type='checkbox'\]\)[^{]*select, textarea\):not\(:focus\)\s*\{\s*border-color:\s*var\(--field-border\);/)
  })

  it('чекбоксы, радио и ползунок рамку не получают', () => {
    for (const type of ['checkbox', 'radio', 'range']) expect(css).toContain(`:not([type='${type}'])`)
  })
})

// UI-21: у .btn / .btn-primary не было ни :hover, ни :active — кнопка не отвечала на наведение и нажатие (в компонентах их тоже нет).
describe('base.css — состояния кнопок (UI-21)', () => {
  const css = readStyles('src/styles/base.css')

  it('у основной кнопки есть :hover и :active — через color-mix от токена акцента, без жёстких цветов', () => {
    const hover = ruleBody(css, '.btn-primary:hover:not(:disabled)')
    const active = ruleBody(css, '.btn-primary:active:not(:disabled)')
    expect(declaration(hover, 'background')).toMatch(/^color-mix\(in srgb, var\(--brand\)/)
    expect(declaration(active, 'background')).toMatch(/^color-mix\(in srgb, var\(--brand\)/)
    expect(declaration(hover, 'background')).not.toBe(declaration(active, 'background'))
  })

  it('у вторичной и обычной кнопки при наведении фон — --surface-hover, при нажатии темнее', () => {
    expect(declaration(ruleBody(css, '.btn-secondary:hover:not(:disabled)'), 'background')).toBe('var(--surface-hover)')
    expect(declaration(ruleBody(css, '.btn-secondary:active:not(:disabled)'), 'background')).toMatch(/^color-mix\(/)
  })

  it('заблокированная кнопка на наведение и нажатие не реагирует (:not(:disabled))', () => {
    expect(css).not.toMatch(/\.btn(?:-primary|-secondary)?:hover\s*\{/)
    expect(css).not.toMatch(/\.btn(?:-primary|-secondary)?:active\s*\{/)
  })

  it('есть общий .sr-only — для заголовков, видимых только скринридеру', () => {
    expect(declaration(ruleBody(css, '.sr-only'), 'position')).toBe('absolute')
    expect(declaration(ruleBody(css, '.sr-only'), 'clip-path')).toBe('inset(50%)')
  })
})
