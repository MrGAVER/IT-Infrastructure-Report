import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useThemeStore, COLOR_SCHEMES } from '../theme'
import { usePreferencesStore } from '../preferences'
import { stubPreferencesApi } from './preferencesApi'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.removeAttribute('data-scheme')
  vi.unstubAllGlobals()
})

describe('useThemeStore', () => {
  it('по умолчанию выбрана первая схема (Бирюза)', () => {
    const theme = useThemeStore()
    expect(theme.schemeId).toBe(COLOR_SCHEMES[0].id)
    expect(theme.scheme.name).toBe('Бирюза')
  })

  it('переключает схему сразу и пишет data-scheme на <html>, не дожидаясь ответа сервера', () => {
    stubPreferencesApi()
    const theme = useThemeStore()
    theme.setScheme('indigo')
    expect(theme.schemeId).toBe('indigo')
    expect(document.documentElement.dataset.scheme).toBe('indigo')
  })

  it('сохраняет выбор на сервере, а не в localStorage браузера', async () => {
    const api = stubPreferencesApi()
    useThemeStore().setScheme('copper')
    await flushPromises()

    expect(api.userPuts).toEqual([{ color_scheme: 'copper' }])
    expect(api.server.user.color_scheme).toBe('copper')
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
  })

  it('игнорирует неизвестный id схемы: ни смены, ни запроса на сервер', async () => {
    const api = stubPreferencesApi()
    const theme = useThemeStore()
    theme.setScheme('nonexistent')
    await flushPromises()
    expect(theme.schemeId).toBe(COLOR_SCHEMES[0].id)
    expect(api.userPuts).toEqual([])
  })

  it('берёт схему из загруженных серверных настроек', () => {
    usePreferencesStore().user = { color_scheme: 'indigo' }
    expect(useThemeStore().schemeId).toBe('indigo')
  })

  it('неизвестная схема в серверных настройках (удалена в новой версии) заменяется схемой по умолчанию', () => {
    usePreferencesStore().user = { color_scheme: 'neon' }
    expect(useThemeStore().schemeId).toBe(COLOR_SCHEMES[0].id)
  })
})
