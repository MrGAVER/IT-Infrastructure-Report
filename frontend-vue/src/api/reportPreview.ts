// Быстрый предпросмотр содержимого шаблона (первые строки/ячейки каждого листа-блока) без
// сохранения шаблона и файла — см. backend/app/api/report_builder.py:preview. Один и тот же
// эндпоинт для обоих форматов, различается только полем format в теле запроса и формой ответа
// (см. GridPreviewResponse/DocxPreviewResponse в api/types.ts) — поэтому здесь два отдельных
// типизированных вызова вместо одной общей функции с размытым типом ответа.
import { api } from './client'
import type { DocxPreviewResponse, GridPreviewResponse } from './types'

export function previewGridConfig(config: Record<string, unknown>, limit = 15) {
  return api.post<GridPreviewResponse>('/report-builder/preview', { format: 'xlsx', config, limit })
}

export function previewDocxConfig(config: Record<string, unknown>, limit = 20) {
  return api.post<DocxPreviewResponse>('/report-builder/preview', { format: 'docx', config, limit })
}
