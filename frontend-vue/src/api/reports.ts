// Генерация отчётов — не CRUD-ресурс: POST возвращает {file_name, download_url},
// сам файл читается отдельным GET (см. backend/app/api/system.py:
// generate_report/generate_audit_log_report/download_report).
import { api, getStoredToken, LONG_REQUEST_TIMEOUT_MS } from './client'

export interface ReportResult {
  file_name: string
  download_url: string
}

/** Формирование отчёта на больших данных может занимать заметно дольше обычных запросов — таймаут по умолчанию (30 с) мал. */
const LONG_OPTIONS = { timeoutMs: LONG_REQUEST_TIMEOUT_MS }

/** POST /api/v1/reports/inventory — регламентный отчёт (Листы 1-4).
 * informationSystemId ограничивает отчёт одной ИС; structuralUnitIds — оборудованием
 * в выбранных структурных единицах и их потомках (см. build_report в reporting.py). */
export function generateInventoryReport(informationSystemId: string | null, structuralUnitIds: string[]) {
  const qs = informationSystemId ? `?information_system_id=${encodeURIComponent(informationSystemId)}` : ''
  return api.post<ReportResult>(`/reports/inventory${qs}`, { structural_unit_ids: structuralUnitIds.length ? structuralUnitIds : null }, LONG_OPTIONS)
}

/** POST /api/v1/reports/structural-appendix — Word-документ «Приложение к структурной схеме»
 * (3 таблицы: назначение линий связи, перечень VLAN, перечень телекоммуникационного оборудования).
 * isName — короткое имя ИС для заголовков («ЕАИС ТО», «ИС ТО»); structuralUnitIds — ограничение
 * оборудованием выбранных структурных единиц, как у регламентированного отчёта
 * (см. services/structural_appendix.py). */
export function generateStructuralAppendixReport(isName: string, structuralUnitIds: string[]) {
  return api.post<ReportResult>('/reports/structural-appendix', {
    is_name: isName,
    structural_unit_ids: structuralUnitIds.length ? structuralUnitIds : null,
  }, LONG_OPTIONS)
}

/** POST /api/v1/reports/audit-log — выгрузка журнала аудита за период. */
export function generateAuditLogReport(dateFrom: string | null, dateTo: string | null) {
  const params = new URLSearchParams()
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.post<ReportResult>(`/reports/audit-log${qs}`, null, LONG_OPTIONS)
}

/** Скачивает уже сгенерированный отчёт, не уводя пользователя со страницы SPA.
 * download_url уже содержит префикс /api/v1 (см. generate_report на бэкенде) —
 * используем как есть, без повторной конкатенации.
 *
 * Фикс п.5: голая <a href="download_url"> (как было раньше) — это обычная навигация браузера,
 * которая никогда не несёт кастомных заголовков. Токен авторизации в этом проекте — намеренно
 * НЕ cookie (см. комментарий в client.ts про allow_credentials=False и отсутствие CSRF-
 * поверхности), а Bearer-заголовок, который добавляет только наш fetch-клиент. При включённой
 * аутентификации такой клик просто получал 401 без единого заголовка Authorization, и браузер
 * показывал общее "файл недоступен на сайте" — вообще без объяснения причины. Теперь файл
 * читается через fetch с тем же заголовком, что и остальные запросы API, и скачивается уже как
 * blob-URL. */
export async function downloadReport(result: ReportResult): Promise<void> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(result.download_url, { headers })
  if (!res.ok) {
    throw new Error(res.status === 401 ? 'Сессия истекла — войдите заново и повторите скачивание' : `Не удалось скачать файл (${res.status})`)
  }
  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = result.file_name
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}
