<script setup lang="ts">
// Источники размещения/IP ИС — унифицированная замена устаревших отдельных таблиц
// ISDevice/ISVM/ISContainer/ISIP (см. комментарий к InformationSystemDetails в api/types.ts).
// Портировано с renderISDetails()/onISSourceTypeChanged()/onISSourceDeviceChanged()/
// onISSourceVMChanged() прежнего vanilla-фронтенда (до 2.60.0) — включая не самую очевидную,
// но сознательную деталь исходной реализации: при типе "ВМ" оба селекта (физический сервер И
// сама ВМ) остаются активны одновременно — выбор ВМ подставляет её хост автоматически, но хост
// можно потом переопределить вручную (это сбросит выбранную ВМ). Сохранено как есть ради
// точного паритета поведения, а не "исправлено" по собственной инициативе.
//
// Модель данных строки (миграция 944bd490d967): единое owner_id вместо прежних трёх отдельных
// FK-полей — при source_type='vm' оно хранит id самой ВМ, а не её хоста, поэтому для описанного
// выше "выбрали сервер, ещё не выбрали ВМ" состояния используется отдельное, НЕ отправляемое на
// backend поле vmHostHint (см. api/types.ts и deviceSelectValue ниже).
//
// IP "ручного" источника — список отдельных полей (ips), а не одно текстовое поле через запятую
// (миграция d8e35a1c7f60, вопрос 3/5 отчёта по анализу БД, согласовано с заказчиком). Список
// рендерится отдельным блоком под основной 4-колоночной сеткой (.source-grid), а не внутри неё —
// переменное число IP сломало бы фиксированную раскладку "8 элементов на 4 колонки" (см.
// комментарий у .row-actions ниже).
import { computed } from 'vue'
import type { Device, ISSourceDraftRow, SourceIpDraftRow, VirtualMachine, Container } from '../api/types'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

const props = defineProps<{ modelValue: ISSourceDraftRow[]; deviceOptions: Device[]; vmOptions: VirtualMachine[]; containerOptions: Container[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: ISSourceDraftRow[]] }>()

function deviceLabel(d: Device): string {
  return d.system_name || d.serial_number
}

// Физический сервер, ВМ и контейнер выбираются через SearchableSelect (поиск вводом текста) —
// списки могут быть длинными. Опции серверов и контейнеров одинаковы для всех строк, поэтому
// считаются один раз (computed), а не на каждую строку.
const deviceSelectOptions = computed<SearchableSelectOption[]>(() => props.deviceOptions.map((d) => ({ value: d.id, label: deviceLabel(d) })))
const containerSelectOptions = computed<SearchableSelectOption[]>(() => props.containerOptions.map((c) => ({ value: c.id, label: c.name })))

// ВМ и контейнеры, уже добавленные в эту ИС другими строками, повторно для размещения не
// предлагаются. Наборы считаются один раз на все строки (а не по проходу на каждую), id берутся
// только у строк соответствующего source_type — owner_id у строки типа "device" это id сервера,
// а не ВМ. У строки типа "vm" без выбранной ВМ owner_id пуст (выбран только сервер-фильтр,
// vmHostHint) — такая строка ничего не занимает.
function ownerIdsOfType(sourceType: ISSourceDraftRow['source_type']): Set<string> {
  const ids = new Set<string>()
  for (const row of props.modelValue) {
    if (row.source_type === sourceType && row.owner_id) ids.add(row.owner_id)
  }
  return ids
}
const usedVmIds = computed(() => ownerIdsOfType('vm'))
const usedContainerIds = computed(() => ownerIdsOfType('container'))

// Все ВМ/контейнеры системы уже добавлены в эту ИС — список новой строки пуст, и без пояснения это выглядит
// как поломка. Если их в системе нет вовсе, пояснения нет: «все добавлены» было бы неправдой.
const allVmsTaken = computed(() => props.vmOptions.length > 0 && props.vmOptions.every((v) => usedVmIds.value.has(v.id)))
const allContainersTaken = computed(() => props.containerOptions.length > 0 && props.containerOptions.every((c) => usedContainerIds.value.has(c.id)))

/** Опция доступна строке, если не занята другой строкой. Собственное значение строки остаётся
 * всегда: подпись текущего выбора SearchableSelect берёт именно из options, а у старых данных с
 * дублем (одна ВМ в двух строках) обе строки должны по-прежнему показывать свою ВМ. */
function isAvailableForRow(optionId: string, row: ISSourceDraftRow, usedIds: ReadonlySet<string>): boolean {
  return optionId === row.owner_id || !usedIds.has(optionId)
}

function containerSelectOptionsFor(row: ISSourceDraftRow): SearchableSelectOption[] {
  return containerSelectOptions.value.filter((o) => isAvailableForRow(o.value, row, usedContainerIds.value))
}

// Значение, показываемое в селекте "физический сервер". При source_type='device' owner_id и есть
// выбранный сервер. При source_type='vm' owner_id хранит id самой ВМ (не её хоста) — если ВМ уже
// выбрана, хост выводится из vmOptions; если ещё нет, используется чисто клиентский vmHostHint
// (см. комментарий у него в api/types.ts) — тот же приём, что раньше давало отдельное поле
// physical_device_id на самой строке, просто теперь это состояние не отправляется на backend.
function deviceSelectValue(row: ISSourceDraftRow): string {
  if (row.source_type === 'device') return row.owner_id
  if (row.source_type === 'vm') return props.vmOptions.find((v) => v.id === row.owner_id)?.physical_device_id ?? row.vmHostHint
  return ''
}

// Из списка исключены ВМ, уже выбранные другими строками (см. usedVmIds). ВМ, чей текущий хост
// совпадает с уже выбранным физическим сервером строки, поднимаются наверх списка — тот же приём, что в vanilla-версии, экономит прокрутку в частом случае
// "сначала выбрали сервер, теперь выбираем его ВМ".
function sortedVms(row: ISSourceDraftRow): VirtualMachine[] {
  const hostId = deviceSelectValue(row)
  const available = props.vmOptions.filter((v) => isAvailableForRow(v.id, row, usedVmIds.value))
  return available.sort((a, b) => {
    const am = hostId && a.physical_device_id === hostId ? 0 : 1
    const bm = hostId && b.physical_device_id === hostId ? 0 : 1
    return am - bm
  })
}

function vmSelectOptions(row: ISSourceDraftRow): SearchableSelectOption[] {
  return sortedVms(row).map((v) => ({ value: v.id, label: v.name }))
}

function emptyRow(): ISSourceDraftRow {
  return { source_type: 'manual', owner_id: '', vmHostHint: '', ips: [], purpose: '', role: '', external_interaction: false }
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
  updateRow(index, { source_type: sourceType as ISSourceDraftRow['source_type'], owner_id: '', vmHostHint: '', ips: [] })
}

function onDeviceChange(index: number, deviceId: string) {
  const row = props.modelValue[index]
  // При типе "ВМ" сервер — только фильтр для списка ВМ (см. deviceSelectValue), сам не
  // сохраняется как owner_id; смена сервера сбрасывает уже выбранную ВМ, как и раньше.
  if (row.source_type === 'vm') updateRow(index, { owner_id: '', vmHostHint: deviceId })
  else updateRow(index, { owner_id: deviceId })
}

function onVmChange(index: number, vmId: string) {
  updateRow(index, { owner_id: vmId, source_type: 'vm', vmHostHint: '' })
}

function addIp(rowIndex: number) {
  const row = props.modelValue[rowIndex]
  updateRow(rowIndex, { ips: [...row.ips, { ip_address: '' }] })
}

function removeIp(rowIndex: number, ipIndex: number) {
  const row = props.modelValue[rowIndex]
  updateRow(rowIndex, { ips: row.ips.filter((_, j) => j !== ipIndex) })
}

function updateIp(rowIndex: number, ipIndex: number, ipAddress: string) {
  const row = props.modelValue[rowIndex]
  const ips: SourceIpDraftRow[] = row.ips.map((x, j) => (j === ipIndex ? { ...x, ip_address: ipAddress } : x))
  updateRow(rowIndex, { ips })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Размещение, IP-адреса и источники данных ИС</b>
      <span class="hint"
        >В одной строке можно выбрать источник из базы или ввести IP вручную. Для сервера/ВМ/контейнера IP подставляются автоматически при генерации
        отчёта.</span
      >
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
        <SearchableSelect
          class="col-device"
          :model-value="deviceSelectValue(row)"
          :options="deviceSelectOptions"
          placeholder="— физический сервер —"
          :disabled="row.source_type !== 'device' && row.source_type !== 'vm'"
          @update:model-value="(v) => onDeviceChange(i, v)"
        />
        <SearchableSelect
          class="col-vm"
          :model-value="row.source_type === 'vm' ? row.owner_id : ''"
          :options="vmSelectOptions(row)"
          :empty-text="allVmsTaken ? 'Все ВМ уже добавлены в эту ИС' : undefined"
          placeholder="— ВМ —"
          :disabled="row.source_type !== 'vm'"
          @update:model-value="(v) => onVmChange(i, v)"
        />
        <SearchableSelect
          class="col-container"
          :model-value="row.source_type === 'container' ? row.owner_id : ''"
          :options="containerSelectOptionsFor(row)"
          :empty-text="allContainersTaken ? 'Все контейнеры уже добавлены в эту ИС' : undefined"
          placeholder="— контейнер —"
          :disabled="row.source_type !== 'container'"
          @update:model-value="(v) => updateRow(i, { owner_id: v })"
        />
        <button v-if="row.source_type === 'manual'" type="button" class="btn-link col-ip" @click="addIp(i)">+ IP-адрес</button>
        <span v-else class="ip-hint col-ip">IP берётся из выбранного оборудования/ВМ</span>
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
            <input
              type="checkbox"
              :checked="row.external_interaction"
              @change="updateRow(i, { external_interaction: ($event.target as HTMLInputElement).checked })"
            />
            <span>Внешнее</span>
          </label>
          <button type="button" class="icon-btn danger" aria-label="Удалить источник" @click="removeRow(i)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>

      <div v-if="row.source_type === 'manual' && row.ips.length" class="manual-ips">
        <div v-for="(ip, j) in row.ips" :key="ip.id ?? j" class="manual-ip-row">
          <input placeholder="IP-адрес" :value="ip.ip_address" @input="updateIp(i, j, ($event.target as HTMLInputElement).value)" />
          <button type="button" class="icon-btn danger" aria-label="Удалить IP" @click="removeIp(i, j)">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
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
/* minmax(0, 1fr): длинная подпись выбранного сервера/ВМ/контейнера не должна распирать колонку
   (у SearchableSelect нет собственной ширины — он занимает всю ячейку грида). */
.source-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
/* Поле SearchableSelect внутри компактной сетки — тот же кегль и высота, что у соседних input/
   select строки (12px, padding 7px 8px), иначе оно выше на 1px и сильнее обрезает подпись.
   Справа остаётся место под крестик очистки и шеврон самого компонента. */
.source-grid :deep(.ss-input-row input) {
  font-size: 12px;
  padding: 7px 40px 7px 8px;
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
.btn-link {
  background: none;
  border: none;
  padding: 0;
  color: var(--brand);
  font-size: 12px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.btn-link:hover {
  text-decoration: underline;
}
.ip-hint {
  font-size: 10.5px;
  color: var(--ink-muted);
  font-style: italic;
}
.manual-ips {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-left: 12px;
  border-left: 2px solid var(--border);
}
.manual-ip-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.manual-ip-row input {
  flex: 1;
  min-width: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}

@media (max-width: 900px) {
  .source-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 560px) {
  .source-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
