<script setup lang="ts">
// Строка «Массовое редактирование» — первая строка той же таблицы портов (общие классы колонок col-select/col-index/col-check/
// col-actions): значения читаются по заголовкам таблицы. Накопленные значения хранит useBulkEdit (поля подключаются через
// v-model), а применение к отмеченным портам — его applyBulkEdit; строка только собирает значения и сообщает о нажатиях.
import type { CatalogItem } from '../api/types'

defineProps<{
  typeOptions: CatalogItem[]
  speedOptions: CatalogItem[]
  /** Есть ли у устройства VLAN: без них выбирать нечего и вместо кнопки показывается пометка. */
  hasVlans: boolean
  /** Краткая сводка выбранных VLAN — подпись кнопки открытия окна выбора. */
  vlanSummary: string
}>()
const emit = defineEmits<{
  'open-vlan-picker': []
  apply: []
}>()
// '' — «не менять».
const typeId = defineModel<string>('typeId', { required: true })
const speedId = defineModel<string>('speedId', { required: true })
// '' — не менять, 'true' / 'false' — включить / выключить.
const management = defineModel<string>('management', { required: true })
const dataTransfer = defineModel<string>('dataTransfer', { required: true })
// '' — не менять, 'access' / 'trunk' — режим порта (п.1.4.3.2).
const vlanMode = defineModel<string>('vlanMode', { required: true })
</script>

<template>
  <tr class="bulk-edit-row">
    <td class="col-select">—</td>
    <td class="col-index">—</td>
    <td class="col-order">—</td>
    <td><b>Массовое редактирование</b></td>
    <td>
      <select v-model="typeId" class="cell-input" aria-label="Тип интерфейса — массовое редактирование">
        <option value="">— не менять —</option>
        <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
      </select>
    </td>
    <td>—</td>
    <td>
      <select v-model="speedId" class="cell-input" aria-label="Скорость — массовое редактирование">
        <option value="">— не менять —</option>
        <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </td>
    <td class="col-check">
      <select v-model="management" class="cell-input bulk-tri-select" aria-label="Управление — массовое редактирование">
        <option value="">—</option>
        <option value="true">Вкл</option>
        <option value="false">Выкл</option>
      </select>
    </td>
    <td class="col-check">
      <select v-model="dataTransfer" class="cell-input bulk-tri-select" aria-label="Передача данных — массовое редактирование">
        <option value="">—</option>
        <option value="true">Вкл</option>
        <option value="false">Выкл</option>
      </select>
    </td>
    <td class="col-vlan-bulk">
      <select v-model="vlanMode" class="cell-input" aria-label="Режим порта — массовое редактирование">
        <option value="">— не менять —</option>
        <option value="trunk">Trunk</option>
        <option value="access">Access</option>
      </select>
      <button v-if="hasVlans" type="button" class="btn btn-secondary vlan-picker-btn" @click="emit('open-vlan-picker')">
        {{ vlanSummary }}
      </button>
      <span v-else class="empty">VLAN не назначены</span>
    </td>
    <td class="col-actions">
      <button
        type="button"
        class="icon-btn"
        title="Применить заполненные поля этой строки к отмеченным галочкой интерфейсам ниже"
        aria-label="Применить к выбранным"
        @click="emit('apply')"
      >
        <svg class="icon"><use href="/icons.svg#i-check" /></svg>
      </button>
    </td>
  </tr>
</template>

<style scoped>
.bulk-edit-row {
  background: var(--surface-2);
}
.bulk-edit-row .cell-input {
  width: 100%;
}
/* Тройной выбор "не менять/вкл/выкл" не помещается в узкую .col-check (рассчитанную на один
   чекбокс 14×14) без переноса — расширяем только для этого select, не трогая ширину самой
   колонки у остальных строк (у них там обычный чекбокс, ему запас не нужен).
   Внимание: .cell-input (стили ниже, общий файл) идёт позже и при равной специфичности перекрывает min-width, так что на деле
   действует его 90px — так было и в DeviceInterfacesEditor.vue до выноса; порядок блоков <style> не менять. */
.bulk-tri-select {
  min-width: 64px;
}
.col-vlan-bulk {
  min-width: 220px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
<style scoped src="../styles/interfaceVlanControls.css"></style>
<style scoped src="../styles/interfaceCellInput.css"></style>
<style scoped src="../styles/interfaceTable.css"></style>
<style scoped src="../styles/interfaceEditorShared.css"></style>
