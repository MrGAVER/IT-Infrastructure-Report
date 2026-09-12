<script setup lang="ts">
// Панель экспорта — три кнопки (drawio/vsdx/svg), скачивание blob (раздел 11 ТЗ: "тот же
// паттерн, что уже используется для скачивания сгенерированных Excel/Word-отчётов" — паттерн
// тот же по СМЫСЛУ (клик -> скачивание файла), но не буквально та же реализация, см. комментарий
// в api/diagrams.ts:exportDiagram про заголовок Authorization).
import type { DiagramExportFormat } from '../../api/diagrams'

const props = defineProps<{ exporting: DiagramExportFormat | null }>()
const emit = defineEmits<{ export: [format: DiagramExportFormat] }>()

const FORMATS: { value: DiagramExportFormat; label: string }[] = [
  { value: 'drawio', label: '.drawio' },
  { value: 'vsdx', label: '.vsdx' },
  { value: 'svg', label: '.svg' },
]
</script>

<template>
  <div class="export-panel">
    <span class="export-label">Экспорт:</span>
    <button
      v-for="f in FORMATS"
      :key="f.value"
      class="btn btn-secondary"
      type="button"
      :disabled="props.exporting !== null"
      @click="emit('export', f.value)"
    >
      <svg class="icon"><use href="/icons.svg#i-file" /></svg>
      {{ props.exporting === f.value ? 'Экспорт…' : f.label }}
    </button>
  </div>
</template>

<style scoped>
.export-panel {
  display: flex;
  align-items: center;
  gap: 8px;
}
.export-label {
  font-size: 11.5px;
  color: var(--ink-muted);
  font-weight: 600;
}
</style>
