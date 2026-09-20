<script setup lang="ts">
// Правка по вопросу 8 отчёта по анализу БД: last_export_format хранился на бэкенде, но никак не
// использовался во фронтенде (мёртвое поле только на запись). UX предложен заказчиком: одна
// кнопка с ПОСЛЕДНИМ использованным форматом (сразу запускает экспорт в нём), справа — маленькая
// кнопка со стрелкой, открывающая список остальных форматов; выбор формата из списка запускает
// экспорт в нём и делает его новым основным. Паттерн закрытия по клику вне — тот же, что в
// SearchableSelect.vue (единственный существующий пример в проекте).
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { DiagramExportFormat } from '../../api/diagrams'

const props = defineProps<{ exporting: DiagramExportFormat | null; lastFormat: DiagramExportFormat | null }>()
const emit = defineEmits<{ export: [format: DiagramExportFormat] }>()

const FORMATS: { value: DiagramExportFormat; label: string }[] = [
  { value: 'drawio', label: '.drawio' },
  { value: 'vsdx', label: '.vsdx' },
  { value: 'svg', label: '.svg' },
]

// Пока диаграмму ни разу не экспортировали, last_export_format = null — основным считается
// первый формат в списке (тот же выбор "по умолчанию — первый пункт", что уже используется в
// других местах проекта, например GROUP_BY_OPTIONS[0] в DiagramCreateModal.vue).
const primaryFormat = computed(() => props.lastFormat ?? FORMATS[0].value)
const primaryLabel = computed(() => FORMATS.find((f) => f.value === primaryFormat.value)?.label ?? primaryFormat.value)
const otherFormats = computed(() => FORMATS.filter((f) => f.value !== primaryFormat.value))

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)

function toggleOpen() {
  open.value = !open.value
}
function closeDropdown() {
  open.value = false
}
function chooseFormat(format: DiagramExportFormat) {
  closeDropdown()
  emit('export', format)
}
function onDocumentClick(event: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(event.target as Node)) closeDropdown()
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="rootEl" class="export-panel">
    <span class="export-label">Экспорт:</span>
    <div class="split-btn">
      <button
        class="btn btn-secondary split-btn-main"
        type="button"
        :disabled="props.exporting !== null"
        @click="emit('export', primaryFormat)"
      >
        <svg class="icon"><use href="/icons.svg#i-file" /></svg>
        {{ props.exporting === primaryFormat ? 'Экспорт…' : `Экспорт ${primaryLabel}` }}
      </button>
      <button
        class="btn btn-secondary split-btn-toggle"
        type="button"
        :disabled="props.exporting !== null"
        aria-label="Другие форматы экспорта"
        @click="toggleOpen"
      >
        <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
      </button>
      <div v-if="open" class="split-btn-menu">
        <button
          v-for="f in otherFormats"
          :key="f.value"
          class="split-btn-menu-item"
          type="button"
          @click="chooseFormat(f.value)"
        >
          {{ props.exporting === f.value ? 'Экспорт…' : f.label }}
        </button>
      </div>
    </div>
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
.split-btn {
  position: relative;
  display: flex;
}
.split-btn-main {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}
.split-btn-toggle {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  border-left: 1px solid var(--border-muted, rgba(0, 0, 0, 0.12));
  padding-left: 6px;
  padding-right: 6px;
}
.split-btn-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  min-width: 100px;
  background: var(--surface, #fff);
  border: 1px solid var(--border-muted, rgba(0, 0, 0, 0.12));
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  z-index: 20;
  overflow: hidden;
}
.split-btn-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 12px;
  border: none;
  background: none;
  font-size: 12.5px;
  cursor: pointer;
}
.split-btn-menu-item:hover {
  background: var(--surface-hover, rgba(0, 0, 0, 0.05));
}
</style>
