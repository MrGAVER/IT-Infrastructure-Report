<script setup lang="ts">
// Источники размещения/IP ИС — унифицированная замена устаревших отдельных таблиц
// ISDevice/ISVM/ISContainer/ISIP (см. комментарий к InformationSystemDetails в api/types.ts).
// Портировано с renderISDetails()/onISSourceTypeChanged()/onISSourceDeviceChanged()/
// onISSourceVMChanged() в frontend/static/information-systems.js — включая не самую очевидную,
// но сознательную деталь исходной реализации: при типе "ВМ" оба селекта (физический сервер И
// сама ВМ) остаются активны одновременно — выбор ВМ подставляет её хост автоматически, но хост
// можно потом переопределить вручную (это сбросит выбранную ВМ). Сохранено как есть ради
// точного паритета поведения, а не "исправлено" по собственной инициативе.
import type { Device, ISSourceDraftRow, VirtualMachine, Container } from '../api/types'

const props = defineProps<{ modelValue: ISSourceDraftRow[]; deviceOptions: Device[]; vmOptions: VirtualMachine[]; containerOptions: Container[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: ISSourceDraftRow[]] }>()

function deviceLabel(d: Device): string {
  return d.system_name || d.serial_number
}

// ВМ, чей текущий хост совпадает с уже выбранным физическим сервером строки, поднимаются
// наверх списка — тот же приём, что в vanilla-версии, экономит прокрутку в частом случае
// "сначала выбрали сервер, теперь выбираем его ВМ".
function sortedVms(row: ISSourceDraftRow): VirtualMachine[] {
  return [...props.vmOptions].sort((a, b) => {
    const am = row.physical_device_id && a.physical_device_id === row.physical_device_id ? 0 : 1
    const bm = row.physical_device_id && b.physical_device_id === row.physical_device_id ? 0 : 1
    return am - bm
  })
}

function emptyRow(): ISSourceDraftRow {
  return { source_type: 'manual', physical_device_id: '', virtual_machine_id: '', container_id: '', ip_address: '', purpose: '', role: '', external_interaction: false }
}

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateRow(index: number, patch: Partial<ISSourceDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

function onTypeChange(index: number, sourceType: string) {
  updateRow(index, { source_type: sourceType as ISSourceDraftRow['source_type'], physical_device_id: '', virtual_machine_id: '', container_id: '', ip_address: '' })
}

function onDeviceChange(index: number, deviceId: string) {
  updateRow(index, { physical_device_id: deviceId, virtual_machine_id: '' })
}

function onVmChange(index: number, vmId: string) {
  const vm = props.vmOptions.find((v) => v.id === vmId)
  updateRow(index, { virtual_machine_id: vmId, source_type: 'vm', physical_device_id: vm?.physical_device_id ?? '' })
}

function ipPlaceholder(row: ISSourceDraftRow): string {
  return row.source_type === 'manual' ? 'IP-адрес (можно несколько через запятую)' : 'IP берётся из выбранного оборудования/ВМ'
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Размещение, IP-адреса и источники данных ИС</b>
      <span class="hint">В одной строке можно выбрать источник из базы или ввести IP вручную. Для сервера/ВМ/контейнера IP подставляются автоматически при генерации отчёта.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">Не добавлено</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="source-card">
      <div class="source-grid">
        <select :value="row.source_type" @change="onTypeChange(i, ($event.target as HTMLSelectElement).value)">
          <option value="manual">Вручную</option>
          <option value="device">Физический сервер / оборудование</option>
          <option value="vm">Виртуальная машина</option>
          <option value="container">Контейнер</option>
        </select>
        <select
          :value="row.physical_device_id"
          :disabled="row.source_type !== 'device' && row.source_type !== 'vm'"
          @change="onDeviceChange(i, ($event.target as HTMLSelectElement).value)"
        >
          <option value="">— физический сервер —</option>
          <option v-for="d in deviceOptions" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
        </select>
        <select :value="row.virtual_machine_id" :disabled="row.source_type !== 'vm'" @change="onVmChange(i, ($event.target as HTMLSelectElement).value)">
          <option value="">— ВМ —</option>
          <option v-for="v in sortedVms(row)" :key="v.id" :value="v.id">{{ v.name }}</option>
        </select>
        <select
          :value="row.container_id"
          :disabled="row.source_type !== 'container'"
          @change="updateRow(i, { container_id: ($event.target as HTMLSelectElement).value })"
        >
          <option value="">— контейнер —</option>
          <option v-for="c in containerOptions" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <input
          class="col-ip"
          :placeholder="ipPlaceholder(row)"
          :disabled="row.source_type !== 'manual'"
          :value="row.ip_address"
          @input="updateRow(i, { ip_address: ($event.target as HTMLInputElement).value })"
        />
        <input placeholder="Назначение" :value="row.purpose" @input="updateRow(i, { purpose: ($event.target as HTMLInputElement).value })" />
        <input placeholder="Роль в ИС" :value="row.role" @input="updateRow(i, { role: ($event.target as HTMLInputElement).value })" />
        <!-- Фикс: чекбокс "Внешнее" и кнопка удаления объединены в одну ячейку грида (.row-actions)
             — раньше это были два отдельных элемента грида, а .source-grid — 4-колоночный: при 9
             элементах в 4 колонках 9-й (кнопка удаления) оставался один на новой строке в 1-й
             колонке и прижимался вправо ВНУТРИ этой узкой ячейки (justify-self:end), визуально
             "сползая" вправо-вниз от чекбокса, который оказывался в конце ПРЕДЫДУЩЕЙ строки. Теперь
             ровно 8 элементов на 4 колонки (2 строки без остатка) на любой ширине, включая
             брейкпоинты ниже (900px/560px), и чекбокс с кнопкой всегда рядом в одной ячейке. -->
        <div class="row-actions">
          <label class="external-check">
            <input type="checkbox" :checked="row.external_interaction" @change="updateRow(i, { external_interaction: ($event.target as HTMLInputElement).checked })" />
            <span>Внешнее</span>
          </label>
          <button type="button" class="icon-btn danger" aria-label="Удалить источник" @click="removeRow(i)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      Источник / IP
    </button>
  </div>
</template>

<style scoped>
.nested-editor {
  grid-column: 1 / -1;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.nested-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nested-head b {
  font-size: 12.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.source-card {
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px;
}
.source-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  align-items: center;
}
.source-grid input,
.source-grid select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
}
.source-grid select:disabled,
.source-grid input:disabled {
  opacity: 0.45;
}
.external-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.row-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
  flex-shrink: 0;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
.add-btn {
  align-self: flex-start;
}

@media (max-width: 900px) {
  .source-grid {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 560px) {
  .source-grid {
    grid-template-columns: 1fr;
  }
}
</style>
