// Генерация отчётов — не CRUD-ресурс: POST возвращает {file_name, download_url},
// сам файл читается отдельным GET (см. backend/app/api/system.py:
// generate_report/generate_audit_log_report/download_report).
import { api } from './client'

export interface ReportResult {
  file_name: string
  download_url: string
}

/** POST /api/v1/reports/inventory — регламентный отчёт (Листы 1-4).
 * informationSystemId ограничивает отчёт одной ИС; structuralUnitIds — оборудованием
 * в выбранных структурных единицах и их потомках (см. build_report в reporting.py). */
export function generateInventoryReport(informationSystemId: string | null, structuralUnitIds: string[]) {
  const qs = informationSystemId ? `?information_system_id=${encodeURIComponent(informationSystemId)}` : ''
  return api.post<ReportResult>(`/reports/inventory${qs}`, { structural_unit_ids: structuralUnitIds.length ? structuralUnitIds : null })
}

/** POST /api/v1/reports/audit-log — выгрузка журнала аудита за период. */
export function generateAuditLogReport(dateFrom: string | null, dateTo: string | null) {
  const params = new URLSearchParams()
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.post<ReportResult>(`/reports/audit-log${qs}`, null)
}

/** Скачивает уже сгенерированный отчёт, не уводя пользователя со страницы SPA.
 * download_url уже содержит префикс /api/v1 (см. generate_report на бэкенде) —
 * используем как есть, без повторной конкатенации. */
export function downloadReport(result: ReportResult) {
  const a = document.createElement('a')
  a.href = result.download_url
  a.download = result.file_name
  document.body.appendChild(a)
  a.click()
  a.remove()
}
