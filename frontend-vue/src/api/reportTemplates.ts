// Шаблоны произвольных отчётов (конструктор) — свой роутер, НЕ /resources/{resource} (см.
// backend/app/api/report_builder.py): у него нестандартные операции (versions/restore,
// duplicate, generate), а config — непрозрачный для API JSON, вся структурная валидация
// выполняется на сервере. listResource/createResource/... из api/client.ts сюда не подходят.
//
// В этой версии Vue-интерфейс управляет ЖИЗНЕННЫМ ЦИКЛОМ шаблона (список, создание, переименование,
// дублирование, удаление, генерация файла, история версий) — визуальный редактор СОДЕРЖИМОГО
// (config.sheets для xlsx / config.blocks для docx, drag-and-drop сетка ячеек) остаётся пока
// только в /legacy (report_builder.js), см. frontend-vue/README.md. Поэтому создание нового
// шаблона здесь заводит МИНИМАЛЬНЫЙ валидный каркас конфигурации (см. seedConfig ниже) — бэкенд
// не принимает пустой config (validate_grid_config/validate_config требуют хотя бы один
// лист/блок с содержимым), а переименование округляет уже существующий config как есть, не
// затрагивая его.
import { api } from './client'
import type { ReportResult } from './reports'
import type { ReportTemplate, ReportTemplateVersion } from './types'

export function listReportTemplates() {
  return api.get<ReportTemplate[]>('/report-templates')
}

export function getReportTemplate(id: string) {
  return api.get<ReportTemplate>(`/report-templates/${id}`)
}

/** Минимальный валидный каркас config для нового шаблона — один лист/блок с названием шаблона в
 * качестве текста, чтобы POST прошёл структурную валидацию на сервере (см. модуль выше).
 * Реальное содержимое пользователь дорабатывает в /legacy до переноса визуального редактора. */
function seedConfig(format: 'xlsx' | 'docx', name: string): Record<string, unknown> {
  const title = name.trim() || 'Новый шаблон'
  if (format === 'docx') return { blocks: [{ type: 'heading', text: title }] }
  return { sheets: [{ title: title.slice(0, 31), columns: [{ width: 30 }], rows: [{ height: 20, repeat: false, cells: [{ col: 0, kind: 'static', text: title }] }] }] }
}

export function createReportTemplate(payload: { name: string; description: string | null; format: 'xlsx' | 'docx' }) {
  return api.post<ReportTemplate>('/report-templates', { ...payload, config: seedConfig(payload.format, payload.name) })
}

/** Переименование/правка описания — format и config округляются как пришли в уже загруженном
 * template (эта форма их не редактирует), см. комментарий модуля выше. */
export function renameReportTemplate(template: ReportTemplate, payload: { name: string; description: string | null }) {
  return api.put<ReportTemplate>(`/report-templates/${template.id}`, { ...payload, format: template.format, config: template.config })
}

export function deleteReportTemplate(id: string) {
  return api.delete<{ status: string }>(`/report-templates/${id}`)
}

export function duplicateReportTemplate(id: string) {
  return api.post<ReportTemplate>(`/report-templates/${id}/duplicate`, null)
}

export function listReportTemplateVersions(templateId: string) {
  return api.get<ReportTemplateVersion[]>(`/report-templates/${templateId}/versions`)
}

export function restoreReportTemplateVersion(templateId: string, versionId: string) {
  return api.post<ReportTemplate>(`/report-templates/${templateId}/versions/${versionId}/restore`, null)
}

/** Формирует файл по шаблону без дополнительных параметров/ограничения структурными единицами —
 * то же, что кнопка "Сформировать" без фильтров в /legacy. Результат скачивается через
 * downloadReport() из api/reports.ts, как и остальные отчёты. */
export function generateReportFromTemplate(id: string) {
  return api.post<ReportResult>(`/report-templates/${id}/generate`, null)
}
