<script setup lang="ts">
// Блок «Открытые порты» раскрытой строки порта — набор КОНКРЕТНОГО интерфейса (раньше был один общий на всё устройство в
// DeviceFormModal.vue) плюс копирование уже введённого набора на другой интерфейс: однотипные порты (uplink-группа, стек
// коммутаторов) незачем набирать вручную заново на каждом. Выбор получателя и само копирование — useRowUiState/useInterfaceRows
// родителя; блок только показывает список портов-получателей и сообщает о выборе.
import { computed } from 'vue'
import type { InterfaceDraftRow, OpenPortDraftRow, ProtocolPortCatalogEntry } from '../api/types'
import OpenPortListEditor from './OpenPortListEditor.vue'

const props = defineProps<{
  /** Все порты устройства: из них строится список получателей копирования (кроме самого порта). */
  rows: InterfaceDraftRow[]
  /** Номер этого порта в rows. */
  index: number
  catalogEntries: ProtocolPortCatalogEntry[]
  /** Открытые порты задаёт группа портов: список только для просмотра, копирование недоступно. */
  managed: boolean
  /** Подсказка о группе, показывается у заблокированного списка. */
  lockNote: string
  /** Порог сворачивания длинных списков (из «Настроек»). */
  collapseAfter: number
  /** Выбранный получатель копирования — номер порта строкой, '' — не выбран. */
  copyTarget: string
}>()
const emit = defineEmits<{
  'update:openPorts': [ports: OpenPortDraftRow[]]
  'set-copy-target': [value: string]
  copy: []
}>()

const openPorts = computed(() => props.rows[props.index]?.open_ports ?? [])
</script>

<template>
  <div class="ports-block">
    <div class="ports-head">
      <b>Открытые порты</b>
      <span v-if="managed" class="group-lock">{{ lockNote }}</span>
      <div v-if="rows.length > 1 && !managed" class="copy-ports-row">
        <select
          class="copy-target-select"
          :value="copyTarget"
          aria-label="Скопировать открытые порты на другой интерфейс"
          @change="emit('set-copy-target', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">Скопировать на порт…</option>
          <template v-for="(other, oi) in rows" :key="other.id ?? oi">
            <option v-if="oi !== index" :value="String(oi)">{{ other.name || `#${oi + 1}` }}</option>
          </template>
        </select>
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="!openPorts.length || !copyTarget"
          title="Скопировать открытые порты этого интерфейса на выбранный"
          @click="emit('copy')"
        >
          <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
          Копировать
        </button>
      </div>
    </div>
    <OpenPortListEditor
      :model-value="openPorts"
      :catalog-entries="catalogEntries"
      :readonly="managed"
      :collapse-after="collapseAfter"
      sorted-unique
      @update:model-value="(v) => emit('update:openPorts', v)"
    />
  </div>
</template>

<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped>
.ports-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.ports-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.ports-head b {
  font-size: 11.5px;
}
.copy-ports-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.copy-target-select {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
}

/* Список открытых портов (корень — .nested-editor) внутри строки порта всегда был с отступом 10px между элементами: правило
   .nested-editor редактора портов перекрывало его собственные 8px (корень вложенного компонента получает scope-атрибут родителя).
   Сохраняем прежний вид явно. */
.ports-block > :deep(.nested-editor) {
  gap: 10px;
}
@media (max-width: 640px) {
  .copy-ports-row {
    flex-wrap: wrap;
    width: 100%;
  }
}
</style>
