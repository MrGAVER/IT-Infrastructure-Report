// Шаблоны отчётов, сетка и docx-конструктор. Часть типов API, см. ./index.ts.

/** GET/POST/PUT /api/v1/report-templates — шаблоны конструктора произвольных отчётов. Свой
 * роутер (backend/app/api/report_builder.py), НЕ /resources/{resource} — у него нестандартные
 * операции (versions/restore, duplicate, generate), см. api/reportTemplates.ts. config —
 * непрозрачный для этого API JSON (структура описана в backend/app/services/report_grid.py для
 * xlsx и report_engine.py для docx); вся структурная валидация выполняется на сервере. */
export interface ReportTemplate {
  id: string
  name: string
  description: string | null
  format: 'xlsx' | 'docx'
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

/** Запись истории версий шаблона — только метаданные, сам config версии наружу не отдаётся
 * (см. list_template_versions в backend/app/api/report_builder.py); восстановление выполняется
 * целиком на сервере через отдельный POST .../restore. */
export interface ReportTemplateVersion {
  id: string
  version_number: number
  name: string
  description: string | null
  format: 'xlsx' | 'docx'
  created_at: string | null
}

/** GET /api/v1/report-builder/entities — метаданные сущностей для конструктора отчётов: поля +
 * связи "один-к-одному" (to_one) / обратные "один-ко-многим" (to_many), см.
 * backend/app/services/report_meta.py:entity_metadata_public. Используется и палитрой полей
 * (построение путей вида relation[].field, см. utils/reportEntityPaths.ts), и панелью источника
 * данных повторяющейся строки грид-редактора (root_entity/expand). */
export interface ReportEntityField {
  name: string
  label: string
  type: string
  is_foreign_key: boolean
}

export interface ReportEntityRelation {
  name: string
  target: string
}

export interface ReportEntityMeta {
  key: string
  label: string
  fields: ReportEntityField[]
  to_one: ReportEntityRelation[]
  to_many: ReportEntityRelation[]
}

/** Формат конфигурации грид-листа (config.sheets[i]) — подробно описан в
 * backend/app/services/report_grid.py; здесь только TS-проекция того же формата один в один,
 * структурная валидация полностью на сервере (см. validate_grid_config). */
export interface GridCellStyle {
  bold?: boolean
  italic?: boolean
  underline?: boolean
  align?: 'left' | 'center' | 'right'
  valign?: 'top' | 'middle' | 'bottom'
  wrap?: boolean
  bg?: string
  color?: string
  border?: boolean
  number_format?: string
}

export type GridCellKind = 'static' | 'field' | 'index' | 'formula'

export interface GridCell {
  col: number
  colspan?: number
  rowspan?: number
  kind: GridCellKind
  text?: string
  path?: string
  separator?: string
  style?: GridCellStyle
}

export type GridFilterOp = 'eq' | 'ne' | 'contains' | 'not_contains' | 'not_empty' | 'is_true' | 'is_false'

export interface GridDataSourceFilter {
  path: string
  op: GridFilterOp
  value: string
}

export interface GridDataSource {
  root_entity: string
  expand: string
  include_empty_expand: boolean
  filters: GridDataSourceFilter[]
  sort_by: string
}

export interface GridRow {
  height: number
  repeat: boolean
  data_source: GridDataSource | null
  cells: GridCell[]
}

export interface GridColumn {
  width: number
}

export interface GridSheet {
  title: string
  columns: GridColumn[]
  rows: GridRow[]
}

export interface GridConfig {
  sheets: GridSheet[]
}

/** Формат конфигурации docx-блоков (config.blocks) — см. backend/app/services/report_engine.py:
 * validate_config/build_docx. filters использует тот же формат {path, op, value}, что и
 * GridDataSourceFilter у повторяющейся строки xlsx — общая структура на обоих форматах. */
export interface DocxTableColumn {
  header: string
  source: 'field' | 'index' | 'static'
  path?: string
  separator?: string
  value?: string
}

export interface DocxHeadingBlock {
  type: 'heading'
  text: string
  level?: number
}

export interface DocxParagraphBlock {
  type: 'paragraph'
  text: string
  align?: 'left' | 'center'
}

export interface DocxPageBreakBlock {
  type: 'page_break'
}

export interface DocxTableBlock {
  type: 'table'
  title?: string
  root_entity: string
  expand?: string
  include_empty_expand?: boolean
  sort_by?: string
  filters: GridDataSourceFilter[]
  columns: DocxTableColumn[]
}

export type DocxBlock = DocxHeadingBlock | DocxParagraphBlock | DocxPageBreakBlock | DocxTableBlock

export interface DocxConfig {
  blocks: DocxBlock[]
}

/** Ответ POST /api/v1/report-builder/preview для format='xlsx' — материализованные физические
 * строки/ячейки каждого листа (повторяющиеся строки уже развёрнуты в отдельные физические
 * строки с реальными значениями, урезано до limit записей на повторение), см.
 * backend/app/services/report_grid.py:preview_grid/_physical_rows. cells внутри одной строки —
 * только те позиции, где реально начинается ячейка (как и в самом редакторе), colspan/rowspan
 * нужно так же учитывать при отрисовке (см. utils/gridCoverage.ts:visibleCellsForRow). */
export interface GridPreviewCell {
  col: number
  colspan: number
  rowspan: number
  value: unknown
  is_datetime: boolean
  style: GridCellStyle
}

export interface GridPreviewRow {
  height: number
  cells: GridPreviewCell[]
}

export interface GridPreviewSection {
  title: string
  error?: string
  n_cols?: number
  rows?: GridPreviewRow[]
  total_records?: number
}

export interface GridPreviewResponse {
  sections: GridPreviewSection[]
}

/** Ответ POST /api/v1/report-builder/preview для format='docx' — по одной секции на блок-таблицу
 * (остальные типы блоков в предпросмотре не участвуют, см.
 * backend/app/services/report_render.py:preview_rows/block_tables). rows — уже отрендеренные
 * значения ячеек (не объекты), total — сколько всего записей нашлось до обрезки limit'ом. */
export interface DocxPreviewSection {
  title: string
  error?: string
  headers?: string[]
  rows?: unknown[][]
  total?: number
}

export interface DocxPreviewResponse {
  sections: DocxPreviewSection[]
}
