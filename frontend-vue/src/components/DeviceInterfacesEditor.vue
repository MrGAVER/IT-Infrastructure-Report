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
// DevicePortsModal.vue делают это по-разному, см. комментарии там) и просто отображается
// чекбоксами; сам компонент ничего не запрашивает и не решает, какие VLAN разрешены.
//
// СОЗНАТЕЛЬНО НЕ ПЕРЕНЕСЕНО в этой версии (см. "Ещё не сделано" во frontend-vue/README.md):
// массовое редактирование выбранных карточек (чекбокс "Выбрать" + общая панель VLAN "будет
// добавлен к выбранным" в vanilla) — самостоятельная область, отдельная от самого назначения
// VLAN на порту.
import { ref } from 'vue'
import type { CatalogItem, InterfaceDraftRow, InterfaceIpDraftRow, VLANDefinition } from '../api/types'
import { vlanLabel } from '../utils/vlan'
import QuickAddButton from './QuickAddButton.vue'

const props = defineProps<{ modelValue: InterfaceDraftRow[]; typeOptions: CatalogItem[]; speedOptions: CatalogItem[]; vlanOptions: VLANDefinition[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: InterfaceDraftRow[]] }>()

// Поля генератора — черновой ввод формы, не часть modelValue (как if-count/if-name-template в
// vanilla). Начальное количество подставляется от уже загруженных интерфейсов один раз при
// монтировании — компонент монтируется уже после загрузки данных (см. DeviceFormModal.vue:
// loadingNested), так что на момент монтирования modelValue уже в актуальном состоянии.
const genCount = ref(String(props.modelValue.length))
const genNameTemplate = ref('eth{n}')
const genTypeId = ref('')
const genSpeedId = ref('')

function emptyRow(): InterfaceDraftRow {
  return { name: '', interface_type_id: '', mac_address: '', speed_id: '', is_management: false, is_data_transfer: false, description: '', vlan_ids: [], ips: [] }
}

function applyTemplate(template: string, n: number): string {
  return template.replaceAll('{n}', String(n)).replaceAll('{n0}', String(n).padStart(2, '0'))
}

// Сохраняет существующие строки по индексу (вместе с их id/ips/vlan_ids) — повторное нажатие
// "Сгенерировать" с другим количеством не должно рвать связь с уже сохранёнными интерфейсами и
// их IP, если индекс совпал; лишь имя/тип/скорость перезаписываются шаблоном/значением по
// умолчанию. Совпадает по смыслу с generateInterfaces() в vanilla-версии.
function generate() {
  const count = Math.max(0, Number(genCount.value) || 0)
  const rows: InterfaceDraftRow[] = Array.from({ length: count }, (_, i) => ({
    ...(props.modelValue[i] ?? emptyRow()),
    name: applyTemplate(genNameTemplate.value || 'eth{n}', i + 1),
    interface_type_id: genTypeId.value,
    speed_id: genSpeedId.value,
  }))
  emit('update:modelValue', rows)
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
        <span>Шаблон имени</span>
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
      <button type="button" class="btn btn-secondary" @click="generate">Сгенерировать</button>
      <button type="button" class="btn btn-secondary" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Интерфейс
      </button>
    </div>

    <div v-if="!modelValue.length" class="empty">Интерфейсы не добавлены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="iface-card">
      <div class="iface-card-head">
        <b>Интерфейс {{ i + 1 }}</b>
        <button type="button" class="icon-btn danger" aria-label="Удалить интерфейс" @click="removeRow(i)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
      <div class="iface-card-grid">
        <label class="field">
          <span>Имя</span>
          <input type="text" :value="row.name" @input="updateRow(i, { name: ($event.target as HTMLInputElement).value })" />
        </label>
        <label class="field">
          <span>Тип</span>
          <select :value="row.interface_type_id" @change="updateRow(i, { interface_type_id: ($event.target as HTMLSelectElement).value })">
            <option value="">— не выбрано —</option>
            <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </label>
        <label class="field">
          <span>MAC</span>
          <input type="text" :value="row.mac_address" @input="updateRow(i, { mac_address: ($event.target as HTMLInputElement).value })" />
        </label>
        <label class="field">
          <span>Скорость</span>
          <select :value="row.speed_id" @change="updateRow(i, { speed_id: ($event.target as HTMLSelectElement).value })">
            <option value="">— не выбрано —</option>
            <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </label>
        <label class="field checkbox-field">
          <input type="checkbox" :checked="row.is_management" @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })" />
          <span>Управление</span>
        </label>
        <label class="field checkbox-field">
          <input type="checkbox" :checked="row.is_data_transfer" @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })" />
          <span>Передача данных</span>
        </label>
        <label class="field field-wide">
          <span>Описание</span>
          <textarea :value="row.description" rows="2" @input="updateRow(i, { description: ($event.target as HTMLTextAreaElement).value })"></textarea>
        </label>
      </div>

      <div class="vlan-block">
        <b>VLAN на порту</b>
        <div v-if="vlanOptions.length" class="vlan-checks">
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
.iface-card {
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.iface-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.iface-card-head b {
  font-size: 12px;
}
.iface-card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
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
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12px;
}
.vlan-block {
  border-top: 1px solid var(--border);
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vlan-block b {
  font-size: 11.5px;
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
  border-top: 1px solid var(--border);
  padding-top: 8px;
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
  background: var(--surface-2);
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
  .iface-card-grid {
    grid-template-columns: 1fr;
  }
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
