import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { readStyles } from '../../__tests__/cssSource'

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
