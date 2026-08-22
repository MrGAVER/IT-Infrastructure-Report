// Стор темы для концепции Б "Диспетчерская" (тёмная NOC-консоль).
//
// Важное дизайн-решение: варьируется только фирменный акцент (--brand) и лёгкий
// оттенок фона — семантические статусные цвета (ok/warn/crit) остаются
// неизменными во всех схемах. Иначе выбор "любимого цвета" мог бы случайно
// сделать акцент неотличимым от предупреждения/тревоги в таблице устройств.
import { defineStore } from 'pinia'

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

const STORAGE_KEY = 'itr.colorScheme'

function readStoredScheme(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && COLOR_SCHEMES.some((s) => s.id === stored)) return stored
  } catch {
    /* localStorage недоступен (приватный режим и т.п.) — используем схему по умолчанию */
  }
  return COLOR_SCHEMES[0].id
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    schemeId: readStoredScheme(),
  }),
  getters: {
    scheme: (state): ColorScheme =>
      COLOR_SCHEMES.find((s) => s.id === state.schemeId) ?? COLOR_SCHEMES[0],
  },
  actions: {
    setScheme(id: string) {
      if (!COLOR_SCHEMES.some((s) => s.id === id)) return
      this.schemeId = id
      this.applyToDocument()
      try {
        localStorage.setItem(STORAGE_KEY, id)
      } catch {
        /* сохранить не удалось — не критично, просто не переживёт перезагрузку */
      }
    },
    /**
     * Переключает атрибут data-scheme на <html> — сами значения переменных
     * (--brand/--brand-soft/--bg) определены в styles/theme.css через
     * [data-scheme="..."] и должны совпадать с hex-значениями в COLOR_SCHEMES
     * выше (COLOR_SCHEMES нужен отдельно для отрисовки образцов цвета в пикере).
     */
    applyToDocument() {
      document.documentElement.dataset.scheme = this.scheme.id
    },
  },
})
