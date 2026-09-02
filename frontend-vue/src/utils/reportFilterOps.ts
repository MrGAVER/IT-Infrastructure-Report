import type { GridFilterOp } from '../api/types'

/** Общий список операторов фильтра источника данных — переиспользуется GridCellInspector.vue
 * (фильтр повторяющейся строки xlsx) и DocxTableBlockEditor.vue (фильтр блока-таблицы docx),
 * т.к. формат фильтра {path, op, value} общий для обоих (см. backend/app/services/report_engine.py:
 * _FILTER_OPS). Порядок соответствует RB_FILTER_OPS в frontend/static/report_builder.js. */
export const FILTER_OPS: Array<[GridFilterOp, string]> = [
  ['eq', 'равно'],
  ['ne', 'не равно'],
  ['contains', 'содержит'],
  ['not_contains', 'не содержит'],
  ['not_empty', 'не пусто'],
  ['is_true', 'да/включено'],
  ['is_false', 'нет/выключено'],
]

/** Операторы, у которых поле "значение" не имеет смысла (см. одноимённую проверку в
 * GridCellInspector.vue/DocxTableBlockEditor.vue и ['not_empty','is_true','is_false'].includes(...)
 * в rbTableColumnRowHTML/фильтрах vanilla-версии). */
export const FILTER_OPS_WITHOUT_VALUE: GridFilterOp[] = ['not_empty', 'is_true', 'is_false']
