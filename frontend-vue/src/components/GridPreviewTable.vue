<script setup lang="ts">
// Read-only отрисовка одной секции предпросмотра xlsx-листа (POST /report-builder/preview,
// см. api/reportPreview.ts) — материализованные физические строки/ячейки с реальными
// значениями, colspan/rowspan уже как в итоговом файле. Использует ту же
// utils/gridCoverage.ts:visibleCellsForRow, что и сама сетка редактора
// (ReportGridEditorView.vue), поэтому объединённые ячейки отображаются идентично тому, что
// увидит пользователь при открытии сформированного .xlsx.
import { computed } from 'vue'
import type { GridPreviewSection } from '../api/types'
import { visibleCellsForRow } from '../utils/gridCoverage'
import ScrollableTableWrap from './ScrollableTableWrap.vue'

const props = defineProps<{ section: GridPreviewSection }>()

const columnCount = computed(() => props.section.n_cols ?? 0)
function rowCells(ri: number) {
  return visibleCellsForRow(props.section.rows ?? [], ri, columnCount.value)
}
function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}
</script>

<template>
  <div class="preview-section">
    <div class="preview-head">
      <b>{{ section.title || '(без названия)' }}</b>
      <span v-if="section.total_records !== undefined && section.rows" class="preview-note"> показано записей: {{ section.total_records }} </span>
    </div>
    <p v-if="section.error" class="preview-error">{{ section.error }}</p>
    <ScrollableTableWrap v-else :label="`Предпросмотр: ${section.title || 'без названия'}`">
      <table class="preview-table">
        <tbody>
          <tr v-for="(_row, ri) in section.rows" :key="ri">
            <td
              v-for="{ col, cell } in rowCells(ri)"
              :key="col"
              :colspan="cell?.colspan || 1"
              :rowspan="cell?.rowspan || 1"
              :style="{ fontWeight: cell?.style?.bold ? 700 : 400, textAlign: cell?.style?.align, background: cell?.style?.bg }"
            >
              {{ cellText(cell?.value) }}
            </td>
          </tr>
        </tbody>
      </table>
    </ScrollableTableWrap>
  </div>
</template>

<style scoped>
.preview-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.preview-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.preview-head b {
  font-size: 12.5px;
}
.preview-note {
  font-size: 11px;
  color: var(--ink-muted);
}
.preview-error {
  font-size: 12px;
  color: var(--status-crit);
  margin: 0;
}
.preview-table {
  border-collapse: collapse;
}
.preview-table td {
  border: 1px solid var(--border);
  padding: 4px 8px;
  font-size: 11.5px;
  white-space: nowrap;
}
</style>
