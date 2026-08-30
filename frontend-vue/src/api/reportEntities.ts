// Метаданные сущностей для конструктора отчётов — палитра полей и панель источника данных
// повторяющейся строки грид-редактора берут отсюда. Отдельный файл от reportTemplates.ts,
// т.к. это самостоятельный, не завязанный на конкретный шаблон ресурс (кэшируется на сервере
// через @lru_cache, см. backend/app/services/report_meta.py — здесь можно грузить один раз при
// открытии редактора, а не при каждом шаблоне).
import { api } from './client'
import type { ReportEntityMeta } from './types'

export function getReportEntities() {
  return api.get<ReportEntityMeta[]>('/report-builder/entities')
}
