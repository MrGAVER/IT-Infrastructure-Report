import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsView from '../../views/SettingsView.vue'
import AuthSettingsPanel from '../../components/AuthSettingsPanel.vue'
import AccountPanel from '../../components/AccountPanel.vue'
import { useAuthStore } from '../../stores/auth'
import { declaration, readSource, readStyles, ruleBody } from '../../__tests__/cssSource'

// UI-03 (ревью merge/review-2158-executors, поток Исполнителя 2): панели «Аутентификация» и «Моя учётная запись» выпадали из стиля
// остальных панелей «Настроек» — scoped-правила SettingsView не доходят до дочерних компонентов. jsdom стили не считает (css: false),
// поэтому проверяется исходник: общий файл, его подключение и отсутствие «своих» заголовков в компонентах. Итоговый computed-размер
// шрифта в настоящем браузере проверяет e2e/filled-data.spec.ts.

const sectionCss = readStyles('src/styles/settings-section.css')
const PANELS = ['src/views/SettingsView.vue', 'src/components/AuthSettingsPanel.vue', 'src/components/AccountPanel.vue']

describe('styles/settings-section.css', () => {
  it('задаёт единый заголовок панели 15px и притушённую подпись .hint', () => {
    expect(declaration(ruleBody(sectionCss, '.settings-section h2'), 'font-size')).toBe('15px')
    expect(declaration(ruleBody(sectionCss, '.settings-section .hint'), 'color')).toBe('var(--ink-muted)')
    expect(declaration(ruleBody(sectionCss, '.settings-section .hint'), 'font-size')).toBe('12.5px')
  })

  it('все правила под .settings-section — иначе h2 и .hint просочились бы на остальные экраны', () => {
    const selectors = [...sectionCss.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(^|})\s*([^{}]+){/g)].map((m) => m[2].trim())
    expect(selectors.length).toBeGreaterThan(0)
    for (const selector of selectors) {
      for (const part of selector.split(',')) expect(part.trim(), `селектор «${part.trim()}»`).toMatch(/^\.settings-section\b/)
    }
  })

  it('файл не scoped и не использует необъявленных токенов с запасными светлыми значениями', () => {
    expect(sectionCss).not.toMatch(/var\(--[a-z0-9-]+,/i)
  })
})

describe.each(PANELS)('%s', (path) => {
  const source = readSource(path)

  it('подключает общий файл стилей панелей', () => {
    expect(source).toContain("import '../styles/settings-section.css'")
  })

  it('не объявляет собственных стилей заголовков и подписей — они в общем файле', () => {
    const styles = readStyles(path)
    expect(styles).not.toMatch(/(^|\s)h2\s*{/)
    expect(styles).not.toMatch(/\.section\s+h[23]\s*{/)
    // Раскладочные уточнения вроде `.setup-token-row .hint { flex-basis }` допустимы, самостоятельное правило `.hint { … }` — нет.
    expect(styles).not.toMatch(/(^|\n)\.hint\s*{/)
  })

  it('не оставляет корневой секции со старым классом .section', () => {
    expect(source).not.toMatch(/<section class="card section/)
  })
})

describe('AuthSettingsPanel — поле пароля (UI-03)', () => {
  it('получает не меньше 300px: плейсхолдер «Пароль (мин. 8 символов, буквы и цифры)» не обрезается', () => {
    const body = ruleBody(readStyles('src/components/AuthSettingsPanel.vue'), ".new-user-row input[type='password']")
    expect(declaration(body, 'flex')).toBe('2 1 300px')
  })

  it('поля строки создания пользователя могут сжиматься (min-width: 0), чтобы не вылезать за карточку на телефоне', () => {
    expect(declaration(ruleBody(readStyles('src/components/AuthSettingsPanel.vue'), '.new-user-row input'), 'min-width')).toBe('0')
  })
})

describe('разметка панелей «Настроек»', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify([]))),
    )
  })

  it('корневая секция каждой панели имеет класс settings-section и собственный h2', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }

    const settings = mount(SettingsView)
    await flushPromises()
    const panels = settings.findAll('section.settings-section')
    // организация, формы, цветовая схема, предпросмотр, журнал аудита (администратору), аутентификация, учётная запись
    expect(panels).toHaveLength(7)
    for (const panel of panels) expect(panel.find('h2').exists()).toBe(true)

    expect(mount(AuthSettingsPanel).find('section.settings-section h2').text()).toBe('Аутентификация')
    expect(mount(AccountPanel).find('section.settings-section h2').text()).toBe('Моя учётная запись')
  })
})
