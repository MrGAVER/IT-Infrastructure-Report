// Срок хранения журнала аудита в форме «Настройки аудита»: разбор введённого значения и подписи.
// Границы и правила — те же, что на сервере (backend/app/schemas.py: AuditSettingsUpdate); сервер всё равно проверяет сам.

/** «не ограничен» для 0, иначе «N дн.». */
export function describeRetention(days: number): string {
  return days === 0 ? 'не ограничен' : `${days} дн.`
}

export type RetentionParse = { ok: true; days: number } | { ok: false; error: string }

/** Разбирает текст поля: целое число от 0 до max. Пусто, дробь, минус, буквы и экспонента («1e2») — ошибка. */
export function parseRetentionDays(raw: string | number, max: number): RetentionParse {
  const text = String(raw).trim()
  if (text === '') return { ok: false, error: 'Укажите срок хранения в днях (0 — не удалять).' }
  if (!/^\d+$/.test(text)) return { ok: false, error: 'Срок хранения — целое число дней, 0 или больше.' }
  const days = Number(text)
  if (days > max) return { ok: false, error: `Срок хранения не может быть больше ${max} дн.` }
  return { ok: true, days }
}
