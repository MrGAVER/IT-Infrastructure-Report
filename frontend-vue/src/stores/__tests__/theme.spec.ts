import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useThemeStore, COLOR_SCHEMES } from '../theme'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.removeAttribute('data-scheme')
})

describe('useThemeStore', () => {
  it('по умолчанию выбрана первая схема (Бирюза)', () => {
    const theme = useThemeStore()
    expect(theme.schemeId).toBe(COLOR_SCHEMES[0].id)
    expect(theme.scheme.name).toBe('Бирюза')
  })

  it('переключает схему и пишет data-scheme на <html>', () => {
    const theme = useThemeStore()
    theme.setScheme('indigo')
    expect(theme.schemeId).toBe('indigo')
    expect(document.documentElement.dataset.scheme).toBe('indigo')
  })

  it('сохраняет выбор в localStorage', () => {
    const theme = useThemeStore()
    theme.setScheme('copper')
    expect(localStorage.getItem('itr.colorScheme')).toBe('copper')
  })

  it('игнорирует неизвестный id схемы', () => {
    const theme = useThemeStore()
    theme.setScheme('nonexistent')
    expect(theme.schemeId).toBe(COLOR_SCHEMES[0].id)
  })

  it('восстанавливает схему из localStorage при следующей инициализации стора', () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    const theme = useThemeStore()
    expect(theme.schemeId).toBe('indigo')
  })
})
