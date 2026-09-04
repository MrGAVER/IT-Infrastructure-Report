import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

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
})
