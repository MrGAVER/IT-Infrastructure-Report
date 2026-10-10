// Стор темы для концепции Б "Диспетчерская" (тёмная NOC-консоль).
//
// Важное дизайн-решение: варьируется только фирменный акцент (--brand) и лёгкий
// оттенок фона — семантические статусные цвета (ok/warn/crit) остаются
// неизменными во всех схемах. Иначе выбор "любимого цвета" мог бы случайно
// сделать акцент неотличимым от предупреждения/тревоги в таблице устройств.
import { defineStore } from 'pinia'
import { usePreferencesStore } from './preferences'

export interface ColorScheme {
  id: string
  name: string
  brand: string
  brandSoft: string
  bgTint: string
}

export const COLOR_SCHEMES: ColorScheme[] = [
  { id: 'teal', name: 'Бирюза', brand: '#33C9A7', brandSoft: '#13342D', bgTint: '#0E1620' },
  { id: 'indigo', name: 'Индиго', brand: '#6C7BFF', brandSoft: '#1E2142', bgTint: '#101527' },
  { id: 'copper', name: 'Медь', brand: '#D97B3F', brandSoft: '#3A2416', bgTint: '#1A1410' },
]

// Выбранная схема хранится на сервере (личная настройка пользователя, см. stores/preferences.ts); здесь —
// только проверка идентификатора и применение к документу. Неизвестный идентификатор (например, схему
// удалили в новой версии) молча заменяется схемой по умолчанию.
export const useThemeStore = defineStore('theme', {
  getters: {
    schemeId(): string {
      const stored = usePreferencesStore().user.color_scheme
      return stored && COLOR_SCHEMES.some((s) => s.id === stored) ? stored : COLOR_SCHEMES[0].id
    },
    scheme(): ColorScheme {
      return COLOR_SCHEMES.find((s) => s.id === this.schemeId) ?? COLOR_SCHEMES[0]
    },
  },
  actions: {
    setScheme(id: string) {
      if (!COLOR_SCHEMES.some((s) => s.id === id)) return
      // Значение применяется сразу (saveUser меняет состояние синхронно), на сервер уходит в фоне.
      void usePreferencesStore().saveUser({ color_scheme: id })
      this.applyToDocument()
    },
    /**
     * Переключает атрибут data-scheme на <html> — сами значения переменных
     * (--brand/--brand-soft/--bg) определены в styles/theme.css через
     * [data-scheme="..."] и должны совпадать с hex-значениями в COLOR_SCHEMES
     * выше (COLOR_SCHEMES нужен отдельно для отрисовки образцов цвета в пикере).
     * После загрузки настроек и при выходе из учётной записи схему применяет watch в main.ts.
     */
    applyToDocument() {
      document.documentElement.dataset.scheme = this.scheme.id
    },
  },
})
