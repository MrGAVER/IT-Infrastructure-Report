// Плановые копии: разбор введённых значений и подписи панели «Резервные копии». Границы и правила — те же, что на сервере
// (backend/app/schemas.py: BackupSettingsUpdate); сервер всё равно проверяет сам.

export type NumberParse = { ok: true; value: number } | { ok: false; error: string }

export interface IntervalLimits {
  min: number
  max: number
}

/** Разбирает интервал в часах: 0 (копии выключены) или число от min до max; допустимы дробные («1,5» и «1.5»). Пусто, минус, буквы и
 * экспонента («1e2») — ошибка. */
export function parseIntervalHours(raw: string | number, { min, max }: IntervalLimits): NumberParse {
  const text = String(raw).trim().replace(',', '.')
  if (text === '') return { ok: false, error: 'Укажите интервал в часах (0 — выключить копии).' }
  if (!/^\d+(\.\d+)?$/.test(text)) return { ok: false, error: 'Интервал — число часов, 0 или больше.' }
  const hours = Number(text)
  if (hours !== 0 && hours < min) return { ok: false, error: `Интервал — 0 (выключить) или не меньше ${min} ч.` }
  if (hours > max) return { ok: false, error: `Интервал не может быть больше ${max} ч.` }
  return { ok: true, value: hours }
}

/** Разбирает число хранимых копий: целое от 1 до max. */
export function parseKeepCount(raw: string | number, max: number): NumberParse {
  const text = String(raw).trim()
  if (text === '') return { ok: false, error: 'Укажите, сколько копий хранить.' }
  if (!/^\d+$/.test(text)) return { ok: false, error: 'Число копий — целое число, 1 или больше.' }
  const keep = Number(text)
  if (keep < 1) return { ok: false, error: 'Хранить нужно не меньше одной копии.' }
  if (keep > max) return { ok: false, error: `Хранить можно не больше ${max} копий.` }
  return { ok: true, value: keep }
}

/** «выключены» для 0, иначе «каждые N ч» (дробные — с запятой: «каждые 1,5 ч»). */
export function describeInterval(hours: number): string {
  return hours === 0 ? 'выключены' : `каждые ${String(hours).replace('.', ',')} ч`
}

/** Размер файла: «512 Б», «1,5 КБ», «12,3 МБ». */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1).replace('.', ',')} ${units[unit]}`
}
