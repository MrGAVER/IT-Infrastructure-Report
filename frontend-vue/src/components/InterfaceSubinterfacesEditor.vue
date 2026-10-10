<script setup lang="ts">
// Редактор подинтерфейсов ОДНОГО порта устройства — логических интерфейсов на отдельном VLAN со
// своими IP-адресами, открытыми портами и ролью (как у маршрутизаторов и межсетевых экранов:
// Gi0/0.10 на VLAN 10 с адресом 10.0.10.1/24). Как и OpenPortListEditor.vue / VmIpListEditor.vue,
// компонент ничего не знает про API и сервер: получает список строк, отдаёт новый список через
// `update:modelValue`; сохранение выполняет форма устройства вместе с портами одним запросом
// (api/deviceInterfaces.ts:persistDeviceInterfaces), а проверка при сохранении — общая с формой
// функция utils/subinterfaces.ts:validateSubinterfaceRows. Здесь только подсказки по ходу ввода.
//
// Правила, которые редактор помогает соблюсти (серверные зеркальны — backend/app/services/crud/
// subinterfaces.py): VLAN подинтерфейса обязателен и берётся из допустимых для устройства
// (vlanOptions), на одном порту один VLAN используется один раз (занятые соседями пункты в списке
// выключены), имя подинтерфейса уникально на устройстве (это проверяет форма при сохранении).
import { computed } from 'vue'
import type { InterfaceIpDraftRow, OpenPortDraftRow, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import { emptySubinterface, reassignSubinterfaceVlan } from '../utils/subinterfaces'
import { vlanLabel } from '../utils/vlan'
import OpenPortListEditor from './OpenPortListEditor.vue'

const props = withDefaults(
  defineProps<{
    modelValue: SubinterfaceDraftRow[]
    /** Имя порта-родителя: из него строится подсказка имени «<порт>.<VLAN>». */
    parentName: string
    /** Допустимые VLAN устройства (тот же список, что у VLAN порта). */
    vlanOptions: VLANDefinition[]
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    /** Все известные VLAN (справочник), включая уже недоступные устройству: по ним для подинтерфейса на снятом VLAN
     * известен номер (подпись в предупреждении, пересчёт автоимени при переносе). Без него — только vlanOptions. */
    vlanCatalog?: VLANDefinition[]
  }>(),
  { protocolPortCatalog: () => [], vlanCatalog: () => [] },
)
const emit = defineEmits<{ 'update:modelValue': [rows: SubinterfaceDraftRow[]] }>()

const sortedVlans = computed(() => [...props.vlanOptions].sort((a, b) => a.vlan_id - b.vlan_id))
const vlanById = computed(() => new Map(props.vlanOptions.map((v) => [v.id, v])))
// Номер и подпись VLAN, в том числе уже недоступного устройству (его нет в vlanOptions, но он есть в справочнике).
const knownVlanById = computed(() => new Map([...props.vlanCatalog, ...props.vlanOptions].map((v) => [v.id, v])))

function updateRow(index: number, patch: Partial<SubinterfaceDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptySubinterface(props.parentName)])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

/** VLAN уже занят другим подинтерфейсом этого порта — повторно выбрать его нельзя (сервер вернёт 422). */
function isVlanTaken(index: number, vlanId: string): boolean {
  return props.modelValue.some((row, i) => i !== index && row.vlan_id === vlanId)
}

/** VLAN строки больше недоступен устройству (убран из VLAN устройства / типа устройства / перенесён в другой
 * домен): строку не теряем молча — показываем предупреждение, а сохранить её можно, лишь выбрав другой VLAN. */
function isStaleVlan(row: SubinterfaceDraftRow): boolean {
  return Boolean(row.vlan_id) && !vlanById.value.has(row.vlan_id)
}

/** Подпись недоступного VLAN подинтерфейса («10 — Серверы») для предупреждения; пусто, если VLAN нет и в справочнике. */
function staleVlanLabel(row: SubinterfaceDraftRow): string {
  const vlan = knownVlanById.value.get(row.vlan_id)
  return vlan ? vlanLabel(vlan) : ''
}

// При выборе VLAN имя подставляется само («Gi0/0.10»), но только если пользователь его не правил:
// имя пустое либо совпадает с подсказкой для предыдущего VLAN — иначе не затираем введённое вручную.
// (То же правило пересчитывает автоимена при переименовании порта — utils/subinterfaces.ts:renameSubinterfacesForPort.)
function onVlanChange(index: number, vlanId: string) {
  const row = props.modelValue[index]
  if (!row) return
  const next = vlanById.value.get(vlanId)
  // Выбрано «— выберите VLAN —»: VLAN снимается, имя не трогаем.
  if (!next) {
    updateRow(index, { vlan_id: vlanId })
    return
  }
  // Прежний VLAN ищем и в справочнике: у подинтерфейса на снятом VLAN он уже не в vlanOptions, но автоимя
  // («Gi0/0.20») при переносе на другой VLAN должно обновиться так же, как при обычной смене.
  const { vlan_id, name } = reassignSubinterfaceVlan(row, props.parentName, knownVlanById.value.get(row.vlan_id), next)
  updateRow(index, { vlan_id, name })
}

/** VLAN устройства, свободные для переноса подинтерфейса: не заняты соседними подинтерфейсами порта. */
function freeVlans(index: number): VLANDefinition[] {
  return sortedVlans.value.filter((v) => !isVlanTaken(index, v.id))
}

// Перенос подинтерфейса с недоступного VLAN на выбранный одним действием: та же смена VLAN, что и в основном списке
// (с пересчётом автоимени), после чего предупреждение исчезает. Список сразу возвращается в исходное положение.
function moveToVlan(index: number, event: Event) {
  const select = event.target as HTMLSelectElement
  const vlanId = select.value
  select.value = ''
  if (vlanId) onVlanChange(index, vlanId)
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

function updateOpenPorts(index: number, rows: OpenPortDraftRow[]) {
  updateRow(index, { open_ports: rows })
}
</script>

<template>
  <div class="sub-block">
    <div class="sub-head">
      <div class="sub-title">
        <b>Подинтерфейсы</b>
        <span class="hint">Логические интерфейсы порта на отдельном VLAN — со своим IP-адресом, открытыми портами и ролью.</span>
      </div>
      <button
        type="button"
        class="btn btn-secondary"
        :disabled="!vlanOptions.length"
        :title="vlanOptions.length ? undefined : 'Для устройства не назначены VLAN — подинтерфейс создаётся на одном из них'"
        @click="addRow"
      >
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Подинтерфейс
      </button>
    </div>

    <div v-if="!modelValue.length" class="empty">
      {{ vlanOptions.length ? 'Подинтерфейсы не добавлены' : 'Подинтерфейсы не добавлены. Чтобы создать, назначьте устройству VLAN.' }}
    </div>

    <div v-for="(sub, i) in modelValue" :key="sub.key" class="sub-card">
      <div class="sub-main">
        <label class="sub-field">
          <span>Имя</span>
          <input type="text" :value="sub.name" placeholder="Например, Gi0/0.10" maxlength="100" aria-label="Имя подинтерфейса" @input="updateRow(i, { name: ($event.target as HTMLInputElement).value })" />
        </label>
        <label class="sub-field">
          <span>VLAN</span>
          <select :value="sub.vlan_id" aria-label="VLAN подинтерфейса" :class="{ 'is-stale': isStaleVlan(sub) }" @change="onVlanChange(i, ($event.target as HTMLSelectElement).value)">
            <option value="">— выберите VLAN —</option>
            <option v-if="isStaleVlan(sub)" :value="sub.vlan_id" disabled>VLAN недоступен устройству</option>
            <option v-for="v in sortedVlans" :key="v.id" :value="v.id" :disabled="isVlanTaken(i, v.id)">{{ vlanLabel(v) }}{{ isVlanTaken(i, v.id) ? ' (занят)' : '' }}</option>
          </select>
        </label>
        <div class="sub-flags">
          <label class="flag">
            <input type="checkbox" :checked="sub.is_management" @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })" />
            Управление
          </label>
          <label class="flag">
            <input type="checkbox" :checked="sub.is_data_transfer" @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })" />
            Передача данных
          </label>
        </div>
        <button type="button" class="icon-btn danger" aria-label="Удалить подинтерфейс" @click="removeRow(i)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>

      <div v-if="isStaleVlan(sub)" class="sub-warn" role="alert">
        <span>
          VLAN этого подинтерфейса<template v-if="staleVlanLabel(sub)"> ({{ staleVlanLabel(sub) }})</template> больше не назначен устройству.
          Перенесите подинтерфейс на другой VLAN или удалите его — иначе сохранить не получится.
        </span>
        <select
          class="sub-move"
          aria-label="Перенести подинтерфейс на VLAN"
          :disabled="!freeVlans(i).length"
          :title="freeVlans(i).length ? undefined : 'Нет свободных VLAN устройства — назначьте устройству VLAN или удалите подинтерфейс'"
          @change="moveToVlan(i, $event)"
        >
          <option value="">Перенести на VLAN…</option>
          <option v-for="v in freeVlans(i)" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
        </select>
      </div>

      <label class="sub-field">
        <span>Описание</span>
        <input type="text" :value="sub.description" placeholder="Необязательно" aria-label="Описание подинтерфейса" @input="updateRow(i, { description: ($event.target as HTMLInputElement).value })" />
      </label>

      <div class="sub-ips">
        <div class="sub-ips-head">
          <b>IP-адреса подинтерфейса</b>
          <button type="button" class="btn btn-secondary" @click="addIp(i)">
            <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
            IP-адрес
          </button>
        </div>
        <div v-if="!sub.ips.length" class="empty">IP-адреса не добавлены</div>
        <div v-for="(ip, j) in sub.ips" :key="ip.id ?? j" class="ip-row">
          <input type="text" placeholder="IP-адрес" aria-label="IP-адрес подинтерфейса" :value="ip.ip_address" @input="updateIp(i, j, { ip_address: ($event.target as HTMLInputElement).value })" />
          <input type="number" min="0" max="32" placeholder="Префикс" aria-label="Префикс" :value="ip.prefix_length" @input="updateIp(i, j, { prefix_length: ($event.target as HTMLInputElement).value })" />
          <input type="text" placeholder="Назначение" aria-label="Назначение IP-адреса" :value="ip.purpose" @input="updateIp(i, j, { purpose: ($event.target as HTMLInputElement).value })" />
          <button type="button" class="icon-btn danger" aria-label="Удалить IP подинтерфейса" @click="removeIp(i, j)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>

      <OpenPortListEditor :model-value="sub.open_ports" :catalog-entries="protocolPortCatalog" sorted-unique @update:model-value="(v) => updateOpenPorts(i, v)" />
    </div>
  </div>
</template>

<style scoped>
.sub-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.sub-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.sub-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sub-title b,
.sub-ips-head b {
  font-size: 11.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 2px 0;
}
.sub-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand, var(--border));
  border-radius: var(--r-s);
  background: var(--surface-1, var(--surface));
}
.sub-main {
  display: grid;
  grid-template-columns: 1.2fr 1.4fr auto auto;
  align-items: end;
  gap: 8px;
}
.sub-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
  min-width: 0;
}
.sub-field input,
.sub-field select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
}
.sub-field select.is-stale {
  border-color: var(--status-crit);
}
.sub-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  padding-bottom: 7px;
}
.flag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
  white-space: nowrap;
}
.flag input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.sub-warn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 11.5px;
  color: var(--status-crit);
}
.sub-move {
  background: var(--surface-2);
  border: 1px solid var(--status-crit);
  border-radius: var(--r-s);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
.sub-ips {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-ips-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

@media (max-width: 720px) {
  .sub-main,
  .ip-row {
    grid-template-columns: 1fr;
  }
  .sub-flags {
    padding-bottom: 0;
  }
}
</style>
