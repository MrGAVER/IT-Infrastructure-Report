<script setup lang="ts">
// Редактор физических/логических интерфейсов устройства — карточки портов, генерация по
// шаблону имени, вложенные IP-адреса интерфейса и назначение VLAN на порту. Портирован с
// наибольшего оставшегося блока vanilla-фронтенда (frontend/static/device-interfaces.js:
// renderInterfaceEditor + interfaceCardHtml + generateInterfaces), т.к. именно интерфейсы
// устройства нужны для организации подключений (Лист 3 отчёта) — без них новое устройство,
// заведённое через этот UI, нельзя было подключить ни к чему без /legacy.
//
// VLAN на порту: список допустимых VLAN приходит готовым в vlanOptions (вычисляется вызывающей
// стороной через api/portVlans.ts:computePortVlanOptions — DeviceFormModal.vue и
// DevicePortsModal.vue делают это по-разному, см. комментарии там) и отображается чекбоксами в
// trunk-режиме или одиночным select'ом в access (см. InterfaceDraftRow.vlan_mode, п.1.4.3.2);
// сам компонент ничего не запрашивает и не решает, какие VLAN разрешены.
//
// Массовое редактирование выбранных карточек ("Выбрать" на каждой + панель "Массовое
// редактирование" сверху) — портировано из bulkInterfaceEditHtml()/applyBulkInterfaceEdit() в
// vanilla-версии. selectedIndices — чисто UI-состояние этого компонента (не часть modelValue,
// как if-count/if-name-template генератора выше): индексы сбрасываются при любом структурном
// изменении списка (добавление/удаление/генерация), чтобы после сдвига индексов старый выбор не
// указывал на другую карточку.
//
// п.1.4: четыре независимых фикса блока "Порты / интерфейсы" по обратной связи пользователя —
// 1.4.1) generate() (кнопка "Сгенерировать") ЗАМЕНЯЕТ существующие строки по индексу — так было
//   и раньше, оставлено как есть для обратной совместимости с уже привычным поведением;
//   appendGenerated() (кнопка "Дополнить") — новая, ДОБАВЛЯЕТ новые строки, не трогая старые;
// 1.4.2) HelpTip рядом с "Шаблон имени" — пояснение по {n}/{n0} по клику, а не только в описании
//   README/памяти проекта;
// 1.4.3.1) addRow() больше не разворачивает новую строку автоматически — VLAN/IP свёрнуты по
//   умолчанию для любой строки, включая только что добавленную;
// 1.4.3.2) InterfaceDraftRow.vlan_mode — access (один VLAN, select) / trunk (чекбоксы, в т.ч.
//   "Все VLAN" одним кликом).
import { ref } from 'vue'
import type { CatalogItem, InterfaceDraftRow, InterfaceIpDraftRow, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { vlanLabel } from '../utils/vlan'
import QuickAddButton from './QuickAddButton.vue'
import HelpTip from './HelpTip.vue'

const props = defineProps<{ modelValue: InterfaceDraftRow[]; typeOptions: CatalogItem[]; speedOptions: CatalogItem[]; vlanOptions: VLANDefinition[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: InterfaceDraftRow[]] }>()
const { notify } = useToast()

// Поля генератора — черновой ввод формы, не часть modelValue (как if-count/if-name-template в
// vanilla). Начальное количество подставляется от уже загруженных интерфейсов один раз при
// монтировании — компонент монтируется уже после загрузки данных (см. DeviceFormModal.vue:
// loadingNested), так что на момент монтирования modelValue уже в актуальном состоянии.
const genCount = ref(String(props.modelValue.length))
const genNameTemplate = ref('eth{n}')
const genTypeId = ref('')
const genSpeedId = ref('')

function emptyRow(): InterfaceDraftRow {
  return {
    name: '',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    // trunk по умолчанию — п.1.4.3.2 ("используются все vlan (по умолчанию) или только
    // некоторые)"); access — осознанный выбор пользователя, а не стартовое состояние.
    vlan_mode: 'trunk',
    ips: [],
  }
}

const TEMPLATE_HELP_TEXT =
  'В шаблоне можно использовать:\n' +
  '{n} — порядковый номер порта: 1, 2, 3…\n' +
  '{n0} — тот же номер с ведущим нулём: 01, 02, 03…\n\n' +
  'Примеры:\n' +
  'eth{n} → eth1, eth2, eth3…\n' +
  'GigabitEthernet0/{n0} → GigabitEthernet0/01, GigabitEthernet0/02…\n\n' +
  'Номер отсчитывается от 1 в пределах одного нажатия "Заменить"/"Добавить" — при "Добавить" '
  + 'продолжает нумерацию от количества уже существующих интерфейсов, а не начинает заново.'

function applyTemplate(template: string, n: number): string {
  return template.replaceAll('{n}', String(n)).replaceAll('{n0}', String(n).padStart(2, '0'))
}

// Сохраняет существующие строки по индексу (вместе с их id/ips/vlan_ids) — повторное нажатие
// "Заменить" с другим количеством не должно рвать связь с уже сохранёнными интерфейсами и их IP,
// если индекс совпал. Совпадает по смыслу с generateInterfaces() в vanilla-версии.
//
// п.3.3, два фикса:
// 1) Если хотя бы одна строка уже содержит реальные данные (не просто пустая карточка,
//    добавленная кнопкой "+ Интерфейс"), генерация без предупреждения перезаписывала бы их
//    шаблонными значениями — теперь сначала спрашиваем подтверждение (тот же паттерн confirm(),
//    что и в DeviceFormModal.vue для конфликтов сохранения).
// 2) genTypeId/genSpeedId, оставленные "— не выбрано —", раньше ВСЕГДА принудительно затирали
//    interface_type_id/speed_id уже существующих строк пустым значением — даже если
//    пользователь нажал "Заменить" только чтобы поменять количество или шаблон имени, а тип
//    со скоростью на строках были выставлены вручную ранее. applyBulkEdit() ниже для того же
//    случая уже трактует пустое значение поля как "не менять" (bulkTypeId.value || row.type) —
//    generate() приведён к тому же принципу.
//
// п.1.4.1: раньше это была ЕДИНСТВЕННАЯ кнопка генератора — "заменить" было единственным
// доступным режимом, добавить N интерфейсов К уже существующим, не трогая их, было нельзя (кроме
// как по одному через "+ Интерфейс"). appendGenerated() ниже — вторая кнопка именно для этого.
function generate() {
  const hasExistingData = props.modelValue.some(
    (row) => row.name.trim() || row.mac_address.trim() || row.description.trim() || row.ips.length || row.vlan_ids.length,
  )
  if (hasExistingData) {
    const count = props.modelValue.length
    const ok = confirm(`Уже заполнено ${count} интерфейс${count === 1 ? '' : 'а(ов)'}. Заменить их шаблонными значениями?`)
    if (!ok) return
  }
  const count = Math.max(0, Number(genCount.value) || 0)
  const rows: InterfaceDraftRow[] = Array.from({ length: count }, (_, i) => {
    const existing = props.modelValue[i] ?? emptyRow()
    return {
      ...existing,
      name: applyTemplate(genNameTemplate.value || 'eth{n}', i + 1),
      interface_type_id: genTypeId.value || existing.interface_type_id,
      speed_id: genSpeedId.value || existing.speed_id,
    }
  })
  selectedIndices.value = new Set()
  expandedIndices.value = new Set()
  emit('update:modelValue', rows)
}

// п.1.4.1: добавляет genCount НОВЫХ интерфейсов к уже существующим, не трогая их вовсе — ни
// имена, ни тип/скорость, ни VLAN/IP. Нумерация в шаблоне имени продолжается от количества уже
// существующих строк (а не начинается заново с 1), чтобы не плодить дублирующиеся имена вроде
// второго eth1 при повторном использовании генератора. Подтверждение не нужно — действие ничего
// не перезаписывает.
function appendGenerated() {
  const count = Math.max(0, Number(genCount.value) || 0)
  if (!count) return
  const startIndex = props.modelValue.length
  const newRows: InterfaceDraftRow[] = Array.from({ length: count }, (_, i) => ({
    ...emptyRow(),
    name: applyTemplate(genNameTemplate.value || 'eth{n}', startIndex + i + 1),
    interface_type_id: genTypeId.value,
    speed_id: genSpeedId.value,
  }))
  selectedIndices.value = new Set()
  emit('update:modelValue', [...props.modelValue, ...newRows])
}

function addRow() {
  selectedIndices.value = new Set()
  // п.1.4.3.1: новая строка НЕ разворачивается автоматически — блок VLAN/IP свёрнут по
  // умолчанию для любой строки, включая только что добавленную (было наоборот: разворачивалась
  // принудительно — см. историю, до этого фикса строка ниже была `expandedIndices.value.add(...)`).
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  selectedIndices.value = new Set()
  expandedIndices.value = new Set()
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateRow(index: number, patch: Partial<InterfaceDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

function addIp(index: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: [...row.ips, { ip_address: '', prefix_length: '', purpose: '' }] })
}

function removeIp(index: number, ipIndex: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.filter((_, j) => j !== ipIndex) })
}

function updateIp(index: number, ipIndex: number, patch: Partial<InterfaceIpDraftRow>) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.map((ip, j) => (j === ipIndex ? { ...ip, ...patch } : ip)) })
}

function toggleVlan(index: number, vlanDefId: string, checked: boolean) {
  const row = props.modelValue[index]
  if (!row) return
  const vlan_ids = checked ? [...row.vlan_ids, vlanDefId] : row.vlan_ids.filter((id) => id !== vlanDefId)
  updateRow(index, { vlan_ids })
}

// п.1.4.3.2: режим порта — access (ровно один VLAN) или trunk (несколько, в т.ч. "все").
function setVlanMode(index: number, mode: 'access' | 'trunk') {
  const row = props.modelValue[index]
  if (!row) return
  if (mode === 'access') {
    // При переключении в access оставляем только первый уже отмеченный VLAN — сохранить
    // несколько было бы некорректным сочетанием (см. validateInterfaceDraftRows).
    updateRow(index, { vlan_mode: 'access', vlan_ids: row.vlan_ids.slice(0, 1) })
  } else {
    updateRow(index, { vlan_mode: 'trunk' })
  }
}

function setAccessVlan(index: number, vlanDefId: string) {
  updateRow(index, { vlan_ids: vlanDefId ? [vlanDefId] : [] })
}

/** "Все VLAN" в trunk-режиме — не отдельный флаг в данных (backend его не хранит), а просто
 * состояние, когда vlan_ids порта покрывает весь текущий vlanOptions. Чекбокс "Все VLAN" —
 * удобный способ проставить/снять это состояние одним кликом, вместо того чтобы отмечать
 * каждый VLAN по отдельности. */
function isAllVlansSelected(vlanIds: string[]): boolean {
  return props.vlanOptions.length > 0 && props.vlanOptions.every((v) => vlanIds.includes(v.id))
}

function toggleAllVlans(index: number, checked: boolean) {
  updateRow(index, { vlan_ids: checked ? props.vlanOptions.map((v) => v.id) : [] })
}

/** Краткая сводка для свёрнутой строки таблицы (ячейка "VLAN / IP") — показывает режим порта,
 * не разворачивая деталь. Для access с ещё не выбранным VLAN — просто "Access", без "0 VLAN"
 * (звучало бы как ошибка, хотя это обычное промежуточное состояние при заполнении формы). */
function vlanCellSummary(row: InterfaceDraftRow): string {
  if (row.vlan_mode === 'access') {
    const vlan = props.vlanOptions.find((v) => v.id === row.vlan_ids[0])
    return vlan ? `Access: ${vlanLabel(vlan)}` : 'Access'
  }
  return `Trunk · ${row.vlan_ids.length} VLAN`
}

const selectedIndices = ref<Set<number>>(new Set())
// п.3.4: какие строки таблицы сейчас показывают развёрнутую панель (VLAN на порту, IP-адреса,
// описание) — вынесены из компактной таблицы под toggle, иначе редко нужные на каждый день поля
// съедали бы всю выгоду от перехода с карточек на таблицу.
const expandedIndices = ref<Set<number>>(new Set())
const bulkTypeId = ref('')
const bulkSpeedId = ref('')
const bulkManagement = ref('') // '' — не менять, 'true'/'false' — включить/выключить
const bulkDataTransfer = ref('')
const bulkVlanMode = ref('') // '' — не менять, 'access'/'trunk' — режим порта (п.1.4.3.2)
const bulkVlanIds = ref<Set<string>>(new Set())

function toggleSelect(index: number, checked: boolean) {
  if (checked) selectedIndices.value.add(index)
  else selectedIndices.value.delete(index)
}

function toggleSelectAll(checked: boolean) {
  selectedIndices.value = checked ? new Set(props.modelValue.map((_, i) => i)) : new Set()
}

function toggleExpand(index: number) {
  if (expandedIndices.value.has(index)) expandedIndices.value.delete(index)
  else expandedIndices.value.add(index)
}

function toggleBulkVlan(vlanDefId: string, checked: boolean) {
  if (checked) bulkVlanIds.value.add(vlanDefId)
  else bulkVlanIds.value.delete(vlanDefId)
}

// Применяет накопленные в панели правки ко всем отмеченным карточкам разом — портировано из
// applyBulkInterfaceEdit() в vanilla-версии. Поля со значением "— не менять —" (пустая строка)
// не трогают соответствующее поле выбранных строк; VLAN добавляется К уже стоящим на порту
// (объединение множеств, не замена) — так же, как в vanilla, где легко случайно снять чужой VLAN
// массовым действием было бы хуже, чем просто ничего не убрать.
function applyBulkEdit() {
  if (!selectedIndices.value.size) {
    notify('Отметьте хотя бы один интерфейс галочкой "Выбрать".', 'error')
    return
  }
  const vlanIds = [...bulkVlanIds.value]
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => {
      if (!selectedIndices.value.has(i)) return row
      const vlan_mode = (bulkVlanMode.value || row.vlan_mode) as 'access' | 'trunk'
      let vlan_ids = vlanIds.length ? Array.from(new Set([...row.vlan_ids, ...vlanIds])) : row.vlan_ids
      // access допускает не более одного VLAN — если массовое действие переключает режим в
      // access (или строка уже была в access, а панель добавляет VLAN), лишние отбрасываем,
      // чтобы не сохранить некорректную комбинацию (см. validateInterfaceDraftRows).
      if (vlan_mode === 'access' && vlan_ids.length > 1) vlan_ids = vlan_ids.slice(0, 1)
      return {
        ...row,
        interface_type_id: bulkTypeId.value || row.interface_type_id,
        speed_id: bulkSpeedId.value || row.speed_id,
        is_management: bulkManagement.value === '' ? row.is_management : bulkManagement.value === 'true',
        is_data_transfer: bulkDataTransfer.value === '' ? row.is_data_transfer : bulkDataTransfer.value === 'true',
        vlan_mode,
        vlan_ids,
      }
    }),
  )
  // Полный сброс панели после применения — та же логика, что и полная перерисовка после
  // applyBulkInterfaceEdit() в vanilla-версии: без сброса "не менять" select бы продолжал
  // показывать уже применённое значение, будто его можно применить ещё раз.
  selectedIndices.value = new Set()
  bulkTypeId.value = ''
  bulkSpeedId.value = ''
  bulkManagement.value = ''
  bulkDataTransfer.value = ''
  bulkVlanMode.value = ''
  bulkVlanIds.value = new Set()
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Порты / интерфейсы</b>
      <span class="hint">Управление отмечается на одном или нескольких интерфейсах — все их IP считаются IP управления.</span>
    </div>

    <div class="generator">
      <label>
        <span>Количество</span>
        <input type="number" min="0" v-model="genCount" />
      </label>
      <label>
        <span>Шаблон имени <HelpTip :text="TEMPLATE_HELP_TEXT" /></span>
        <input type="text" v-model="genNameTemplate" placeholder="eth{n}" />
      </label>
      <label>
        <span>Тип по умолчанию</span>
        <div class="lookup-row">
          <select v-model="genTypeId">
            <option value="">— не выбрано —</option>
            <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <QuickAddButton resource="interface-types" title="Тип интерфейса" @created="(r) => (genTypeId = r.id)" />
        </div>
      </label>
      <label>
        <span>Скорость по умолчанию</span>
        <div class="lookup-row">
          <select v-model="genSpeedId">
            <option value="">— не выбрано —</option>
            <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <QuickAddButton resource="interface-speeds" title="Скорость интерфейса" @created="(r) => (genSpeedId = r.id)" />
        </div>
      </label>
      <div class="generator-actions">
        <button type="button" class="btn btn-secondary" @click="generate">Сгенерировать</button>
        <button type="button" class="btn btn-secondary" @click="appendGenerated">Дополнить</button>
      </div>
    </div>
    <span class="hint generator-hint">«Сгенерировать» заменяет уже добавленные интерфейсы шаблонными значениями; «Дополнить» добавляет новые вдобавок к уже существующим, не изменяя их (п.1.4.1).</span>

    <div v-if="modelValue.length" class="bulk-edit-bar">
      <b>Массовое редактирование</b>
      <label class="if-select-label">
        <input type="checkbox" :checked="selectedIndices.size === modelValue.length" @change="toggleSelectAll(($event.target as HTMLInputElement).checked)" />
        <span>Выбрать все</span>
      </label>
      <label class="bulk-field">
        <span>Тип интерфейса</span>
        <select v-model="bulkTypeId">
          <option value="">— не менять —</option>
          <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </label>
      <label class="bulk-field">
        <span>Скорость</span>
        <select v-model="bulkSpeedId">
          <option value="">— не менять —</option>
          <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </label>
      <label class="bulk-field">
        <span>Управление</span>
        <select v-model="bulkManagement">
          <option value="">— не менять —</option>
          <option value="true">Включить</option>
          <option value="false">Выключить</option>
        </select>
      </label>
      <label class="bulk-field">
        <span>Передача данных</span>
        <select v-model="bulkDataTransfer">
          <option value="">— не менять —</option>
          <option value="true">Включить</option>
          <option value="false">Выключить</option>
        </select>
      </label>
      <label class="bulk-field">
        <span>Режим порта</span>
        <select v-model="bulkVlanMode">
          <option value="">— не менять —</option>
          <option value="trunk">Trunk</option>
          <option value="access">Access</option>
        </select>
      </label>
      <div class="bulk-field bulk-field-wide">
        <span>VLAN на порту (будет добавлен к выбранным)</span>
        <div v-if="vlanOptions.length" class="vlan-checks">
          <label v-for="v in vlanOptions" :key="v.id" class="vlan-check">
            <input type="checkbox" :checked="bulkVlanIds.has(v.id)" @change="toggleBulkVlan(v.id, ($event.target as HTMLInputElement).checked)" />
            {{ vlanLabel(v) }}
          </label>
        </div>
        <span v-else class="empty">VLAN не назначены</span>
      </div>
      <button type="button" class="btn btn-secondary" @click="applyBulkEdit">Применить к выбранным</button>
    </div>

    <div v-if="modelValue.length" class="iface-list-head">
      <b>Список интерфейсов</b>
      <button type="button" class="btn btn-secondary" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Интерфейс
      </button>
    </div>

    <div v-if="!modelValue.length" class="empty">
      Интерфейсы не добавлены
      <button type="button" class="btn btn-secondary" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Интерфейс
      </button>
    </div>

    <!-- п.3.4: список интерфейсов — компактная таблица вместо карточек на каждый интерфейс;
         редко нужные при первом взгляде поля (VLAN на порту, IP-адреса, описание) убраны под
         toggle в развёрнутую строку, чтобы таблица помещалась на экран без прокрутки даже при
         десятке портов. -->
    <div v-else class="iface-table-wrap">
      <table class="iface-table">
        <thead>
          <tr>
            <th class="col-select">
              <input
                type="checkbox"
                :checked="selectedIndices.size === modelValue.length"
                aria-label="Выбрать все интерфейсы"
                @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th class="col-index">#</th>
            <th>Имя</th>
            <th>Тип</th>
            <th>MAC</th>
            <th>Скорость</th>
            <th class="col-check">Упр.</th>
            <th class="col-check">Данные</th>
            <th>VLAN / IP</th>
            <th class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, i) in modelValue" :key="row.id ?? i">
            <tr class="iface-row">
              <td class="col-select">
                <input
                  type="checkbox"
                  :checked="selectedIndices.has(i)"
                  aria-label="Выбрать интерфейс"
                  @change="toggleSelect(i, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td class="col-index">{{ i + 1 }}</td>
              <td>
                <input type="text" class="cell-input" v-truncate-tooltip="row.name" :value="row.name" @input="updateRow(i, { name: ($event.target as HTMLInputElement).value })" />
              </td>
              <td>
                <select class="cell-input" :value="row.interface_type_id" @change="updateRow(i, { interface_type_id: ($event.target as HTMLSelectElement).value })">
                  <option value="">— не выбрано —</option>
                  <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
                </select>
              </td>
              <td>
                <input type="text" class="cell-input" v-truncate-tooltip="row.mac_address" :value="row.mac_address" @input="updateRow(i, { mac_address: ($event.target as HTMLInputElement).value })" />
              </td>
              <td>
                <select class="cell-input" :value="row.speed_id" @change="updateRow(i, { speed_id: ($event.target as HTMLSelectElement).value })">
                  <option value="">— не выбрано —</option>
                  <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
                </select>
              </td>
              <td class="col-check">
                <input type="checkbox" :checked="row.is_management" @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })" />
              </td>
              <td class="col-check">
                <input type="checkbox" :checked="row.is_data_transfer" @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })" />
              </td>
              <td>
                <button type="button" class="expand-toggle" @click="toggleExpand(i)">
                  <span v-truncate-tooltip>{{ vlanCellSummary(row) }} · {{ row.ips.length }} IP</span>
                  <svg class="icon chev" :class="{ open: expandedIndices.has(i) }"><use href="/icons.svg#i-chevd" /></svg>
                </button>
              </td>
              <td class="col-actions">
                <button type="button" class="icon-btn danger" aria-label="Удалить интерфейс" @click="removeRow(i)">
                  <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                </button>
              </td>
            </tr>
            <tr v-if="expandedIndices.has(i)" class="iface-detail-row">
              <td colspan="10">
                <div class="iface-detail">
                  <label class="field field-wide">
                    <span>Описание</span>
                    <textarea :value="row.description" rows="2" @input="updateRow(i, { description: ($event.target as HTMLTextAreaElement).value })"></textarea>
                  </label>

                  <div class="vlan-block">
                    <div class="vlan-mode-row">
                      <b>Режим порта</b>
                      <label class="radio-inline">
                        <input
                          type="radio"
                          :name="`vlan-mode-${i}`"
                          :checked="row.vlan_mode !== 'access'"
                          @change="setVlanMode(i, 'trunk')"
                        />
                        Trunk
                      </label>
                      <label class="radio-inline">
                        <input
                          type="radio"
                          :name="`vlan-mode-${i}`"
                          :checked="row.vlan_mode === 'access'"
                          @change="setVlanMode(i, 'access')"
                        />
                        Access
                      </label>
                    </div>

                    <template v-if="row.vlan_mode === 'access'">
                      <div v-if="vlanOptions.length" class="field">
                        <span>VLAN порта (access — ровно один)</span>
                        <select :value="row.vlan_ids[0] ?? ''" @change="setAccessVlan(i, ($event.target as HTMLSelectElement).value)">
                          <option value="">— не выбрано —</option>
                          <option v-for="v in vlanOptions" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
                        </select>
                      </div>
                      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
                    </template>
                    <template v-else>
                      <div v-if="vlanOptions.length" class="vlan-checks">
                        <label class="vlan-check vlan-check-all">
                          <input
                            type="checkbox"
                            :checked="isAllVlansSelected(row.vlan_ids)"
                            @change="toggleAllVlans(i, ($event.target as HTMLInputElement).checked)"
                          />
                          <b>Все VLAN</b>
                        </label>
                        <label v-for="v in vlanOptions" :key="v.id" class="vlan-check">
                          <input
                            type="checkbox"
                            :checked="row.vlan_ids.includes(v.id)"
                            @change="toggleVlan(i, v.id, ($event.target as HTMLInputElement).checked)"
                          />
                          {{ vlanLabel(v) }}
                        </label>
                      </div>
                      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
                    </template>
                  </div>

                  <div class="ip-block">
                    <div class="ip-head">
                      <b>IP-адреса интерфейса</b>
                      <button type="button" class="btn btn-secondary" @click="addIp(i)">
                        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                        IP-адрес
                      </button>
                    </div>
                    <div v-if="!row.ips.length" class="empty">IP-адреса не добавлены</div>
                    <div v-for="(ip, j) in row.ips" :key="ip.id ?? j" class="ip-row">
                      <input type="text" placeholder="IP-адрес" :value="ip.ip_address" @input="updateIp(i, j, { ip_address: ($event.target as HTMLInputElement).value })" />
                      <input
                        type="number"
                        min="0"
                        max="128"
                        placeholder="Префикс"
                        :value="ip.prefix_length"
                        @input="updateIp(i, j, { prefix_length: ($event.target as HTMLInputElement).value })"
                      />
                      <input type="text" placeholder="Назначение" :value="ip.purpose" @input="updateIp(i, j, { purpose: ($event.target as HTMLInputElement).value })" />
                      <button type="button" class="icon-btn danger" aria-label="Удалить IP интерфейса" @click="removeIp(i, j)">
                        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                      </button>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
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
.generator {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.generator label > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.generator-actions {
  display: flex;
  gap: 8px;
}
.generator-hint {
  display: block;
  margin-top: -4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator input,
.generator select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 130px;
}
.generator .lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.generator .lookup-row select {
  width: 130px;
}
.bulk-edit-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 14px;
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: var(--r-s);
}
.bulk-edit-bar > b {
  flex-basis: 100%;
  font-size: 11.5px;
}
.bulk-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.bulk-field select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 150px;
}
.bulk-field-wide {
  flex: 1 1 100%;
}
.if-select-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-muted);
}
.if-select-label input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.iface-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.iface-list-head b {
  font-size: 12px;
}
.empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
/* п.3.4/3.5: компактная таблица интерфейсов вместо карточки на каждый порт; кнопка
   "+ Интерфейс" (п.3.5) теперь стоит в шапке этого же блока, а не среди полей генератора
   выше — она относится к списку, а не к настройкам массовой генерации. */
.iface-table-wrap {
  overflow-x: auto;
}
.iface-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.iface-table th {
  text-align: left;
  font-weight: 600;
  color: var(--ink-muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  padding: 0 6px 6px;
  white-space: nowrap;
}
.iface-table td {
  padding: 4px 6px;
  vertical-align: middle;
  border-top: 1px solid var(--border);
}
.iface-table .col-select,
.iface-table .col-index,
.iface-table .col-check,
.iface-table .col-actions {
  width: 1%;
  white-space: nowrap;
  text-align: center;
}
.iface-table .col-select input,
.iface-table .col-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.iface-table .col-index {
  color: var(--ink-muted);
}
.cell-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 7px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 90px;
  box-sizing: border-box;
}
.expand-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 4px 2px;
  font-size: 11.5px;
  color: var(--ink-muted);
  cursor: pointer;
  white-space: nowrap;
}
.expand-toggle:hover {
  color: var(--ink);
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform 0.15s;
  flex-shrink: 0;
}
.chev.open {
  transform: rotate(180deg);
}
.iface-detail-row td {
  border-top: none;
  padding: 0 6px 10px;
}
.iface-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field-wide {
  grid-column: 1 / -1;
}
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.vlan-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vlan-block b {
  font-size: 11.5px;
}
.vlan-mode-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.radio-inline {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.radio-inline input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
  margin: 0;
}
.vlan-check-all {
  padding-right: 10px;
  margin-right: 4px;
  border-right: 1px solid var(--border);
}
.vlan-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.vlan-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
}
.vlan-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.ip-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ip-head b {
  font-size: 11.5px;
}
.ip-row {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 640px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
