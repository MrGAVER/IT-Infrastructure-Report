<script setup lang="ts">
// Общие настройки VLAN стека (кластера): IP-адрес, префикс и «Управление» вводятся один раз и записываются каждому
// устройству стека. Блок показывается и в форме стека, и в форме самого устройства (если оно в стеке) — это один и тот же
// компонент с одним источником данных (GET/PUT/DELETE /device-stacks/{id}/vlans).
//
// Пока настройка задана, у участников эти значения по отдельности не редактируются (форма устройства блокирует поля, а
// сервер возвращает 409). Расхождение, возникшее в обход (например, VLAN переписала операция домена), видно как
// «значения отличаются» — «Применить ко всем» приводит устройства к настройке. Снятие настройки — отдельное действие с
// подтверждением (StackVlanRemoveDialog): по умолчанию значения на устройствах остаются.
// Родителям: update:state — свежее состояние после каждой загрузки/изменения (по нему форма устройства блокирует поля),
// applied — настройка записана устройствам, removed — настройка снята (fromDevices — VLAN убран и у устройств).
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { DeviceStackVlans, StackVlanOption, StackVlanRow } from '../api/types'
import { useToast } from '../composables/useToast'
import { matchesSharedSetting, sharedSettingPayload, stackVlanStatus, validateSharedIp } from '../utils/stackVlans'
import SearchableSelect from './SearchableSelect.vue'
import StackVlanRemoveDialog from './StackVlanRemoveDialog.vue'

const props = defineProps<{
  stackId: string
  /** Меняется при перезагрузке состава стека (добавили/убрали участника, сохранили устройство) — блок перечитывает настройки. */
  reloadToken: number
}>()
const emit = defineEmits<{
  'update:state': [state: DeviceStackVlans]
  applied: [state: DeviceStackVlans]
  removed: [info: { vlanId: string; fromDevices: boolean; state: DeviceStackVlans }]
}>()
const { notify } = useToast()

/** Строка блока: server — применённая настройка (null у строки, добавленной в форме и ещё не применённой); ip/prefix/management — вводимое. */
interface DraftRow {
  vlanId: string
  label: string
  server: StackVlanRow | null
  ip: string
  prefix: string
  management: boolean
  busy: boolean
  error: string | null
}

const rows = ref<DraftRow[]>([])
const available = ref<StackVlanOption[]>([])
const stackName = ref('')
const memberCount = ref(0)
const loading = ref(false)
const loadError = ref<string | null>(null)
const pickedVlanId = ref('')
const removing = ref<DraftRow | null>(null)
const removeBusy = ref(false)
const removeError = ref<string | null>(null)

function vlanText(number: number, name: string): string {
  return `${number} — ${name}`
}

function draftFromServer(row: StackVlanRow): DraftRow {
  return {
    vlanId: row.vlan_id,
    label: vlanText(row.vlan_number, row.vlan_name),
    server: row,
    ip: row.ip_address ?? '',
    prefix: row.prefix_length === null ? '' : String(row.prefix_length),
    management: row.is_management,
    busy: false,
    error: null,
  }
}

function takeState(res: DeviceStackVlans) {
  available.value = res.available ?? []
  stackName.value = res.stack_name ?? ''
  memberCount.value = res.member_count ?? 0
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const res = await api.get<DeviceStackVlans>(`/device-stacks/${props.stackId}/vlans`)
    rows.value = (res.items ?? []).map(draftFromServer)
    takeState(res)
    pickedVlanId.value = ''
    emit('update:state', { ...res, items: res.items ?? [], available: res.available ?? [] })
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Не удалось загрузить настройки VLAN стека'
  } finally {
    loading.value = false
  }
}

watch(() => [props.stackId, props.reloadToken], load, { immediate: true })

// Ещё не добавленные в блок VLAN, которые можно сделать общими (список приходит с сервера, уже с учётом доменов VLAN).
const pickOptions = computed(() => {
  const taken = new Set(rows.value.map((r) => r.vlanId))
  return available.value.filter((v) => !taken.has(v.vlan_id)).map((v) => ({ value: v.vlan_id, label: vlanText(v.vlan_number, v.vlan_name) }))
})

/** Новая строка подставляет то, на чём уже сошлись устройства: адрес с префиксом и «Управление» (включено хотя бы у одного — значит у всех). */
function addRow() {
  const option = available.value.find((v) => v.vlan_id === pickedVlanId.value)
  if (!option) return
  rows.value.push({
    vlanId: option.vlan_id,
    label: vlanText(option.vlan_number, option.vlan_name),
    server: null,
    ip: option.ip_address ?? '',
    prefix: option.prefix_length === null ? '' : String(option.prefix_length),
    management: option.is_management,
    busy: false,
    error: null,
  })
  pickedVlanId.value = ''
}

function inputError(row: DraftRow): string | null {
  return validateSharedIp(row.ip, row.prefix)
}

function canApply(row: DraftRow): boolean {
  return !row.busy && inputError(row) === null && !matchesSharedSetting(row.server, row.ip, row.prefix, row.management)
}

/** Подставляет свежее состояние сервера: применённая строка пересоздаётся целиком, остальные сохраняют вводимые значения. */
function mergeServerState(res: DeviceStackVlans, appliedVlanId: string) {
  const byId = new Map((res.items ?? []).map((item) => [item.vlan_id, item]))
  rows.value = rows.value.map((r) => {
    const fresh = byId.get(r.vlanId)
    if (r.vlanId === appliedVlanId && fresh) return draftFromServer(fresh)
    return fresh ? { ...r, server: fresh } : r
  })
  takeState(res)
}

async function apply(row: DraftRow) {
  const problem = inputError(row)
  if (problem) {
    row.error = problem
    return
  }
  row.busy = true
  row.error = null
  try {
    const res = await api.put<DeviceStackVlans>(`/device-stacks/${props.stackId}/vlans/${row.vlanId}`, sharedSettingPayload(row.ip, row.prefix, row.management))
    mergeServerState(res, row.vlanId)
    notify(`VLAN ${row.label}: настройка применена ко всем устройствам стека`, 'success')
    emit('update:state', res)
    emit('applied', res)
  } catch (err) {
    row.error = err instanceof Error ? err.message : 'Не удалось применить настройку ко всем устройствам стека'
  } finally {
    row.busy = false
  }
}

/** Строка без применённой настройки просто убирается из формы; применённая — после подтверждения в диалоге. */
function askRemove(row: DraftRow) {
  if (!row.server) {
    rows.value = rows.value.filter((r) => r !== row)
    return
  }
  removeError.value = null
  removing.value = row
}

async function confirmRemove(fromDevices: boolean) {
  const row = removing.value
  if (!row) return
  removeBusy.value = true
  removeError.value = null
  try {
    const res = await api.delete<DeviceStackVlans>(`/device-stacks/${props.stackId}/vlans/${row.vlanId}?remove_from_devices=${fromDevices}`)
    // Настройки больше нет: строка исчезает из списка, а VLAN появляется среди доступных для выбора.
    rows.value = rows.value.filter((r) => r.vlanId !== row.vlanId)
    takeState(res)
    removing.value = null
    notify(fromDevices ? `VLAN ${row.label} снят со стека и убран у его устройств` : `Общая настройка VLAN ${row.label} снята, значения на устройствах сохранены`, 'success')
    emit('update:state', res)
    emit('removed', { vlanId: row.vlanId, fromDevices, state: res })
  } catch (err) {
    removeError.value = err instanceof Error ? err.message : 'Не удалось снять настройку'
  } finally {
    removeBusy.value = false
  }
}

function memberValue(m: { assigned: boolean; ip_address: string | null; prefix_length: number | null; is_management: boolean }): string {
  if (!m.assigned) return 'VLAN не назначен'
  const address = !m.ip_address ? 'адрес не задан' : m.prefix_length === null ? m.ip_address : `${m.ip_address}/${m.prefix_length}`
  return m.is_management ? `${address}, «Управление»` : address
}
</script>

<template>
  <div class="nested-editor field-wide" data-testid="stack-vlan-ip-editor">
    <div class="nested-head">
      <b>Общие настройки VLAN стека{{ stackName ? ` «${stackName}»` : '' }}</b>
      <span class="hint">
        IP-адрес (IPv4), префикс и «Управление» задаются один раз и записываются каждому устройству стека — например, общий адрес кластера.
        Пока настройка задана, у устройств эти значения по отдельности не меняются. Недостающие назначения VLAN создаются.
      </span>
    </div>

    <div v-if="loadError" class="form-error" role="alert">{{ loadError }}</div>
    <p v-else-if="loading && !rows.length" class="empty">Загрузка настроек VLAN стека…</p>
    <p v-else-if="memberCount === 0" class="empty" data-testid="stack-vlan-no-members">Добавьте устройства в стек, чтобы задать им общие настройки VLAN.</p>
    <template v-else>
      <p v-if="!rows.length" class="empty">Общие настройки VLAN не заданы. Добавьте VLAN ниже.</p>

      <div v-for="row in rows" :key="row.vlanId" class="vlan-block" data-testid="stack-vlan-row">
        <div class="vlan-row">
          <span class="vlan-label" :title="row.label">{{ row.label }}</span>
          <input
            v-model.trim="row.ip"
            type="text"
            class="col-ip"
            placeholder="IP-адрес"
            data-testid="stack-vlan-ip"
            @keydown.enter.prevent="canApply(row) && apply(row)"
          />
          <!-- :value/@input, а не v-model: у type="number" v-model приводит ввод к числу, а черновик хранит префикс строкой. -->
          <input
            :value="row.prefix"
            type="number"
            min="0"
            max="32"
            class="col-prefix"
            placeholder="Префикс"
            data-testid="stack-vlan-prefix"
            @input="row.prefix = ($event.target as HTMLInputElement).value"
            @keydown.enter.prevent="canApply(row) && apply(row)"
          />
          <label class="col-mgmt">
            <input v-model="row.management" type="checkbox" data-testid="stack-vlan-management" />
            Управление
          </label>
          <button type="button" class="btn btn-secondary" :disabled="!canApply(row)" data-testid="stack-vlan-apply" @click="apply(row)">
            Применить ко всем
          </button>
          <button
            type="button"
            class="icon-btn danger"
            :aria-label="row.server ? 'Снять общую настройку' : 'Убрать строку'"
            :title="row.server ? 'Снять общую настройку' : 'Убрать строку'"
            data-testid="stack-vlan-remove"
            @click="askRemove(row)"
          >
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
        <div class="status-line">
          <span class="status" :class="`status-${stackVlanStatus(row.server).kind}`" data-testid="stack-vlan-status">{{ stackVlanStatus(row.server).text }}</span>
          <details v-if="row.server && !row.server.is_uniform" class="by-device">
            <summary>По устройствам</summary>
            <ul>
              <li v-for="m in row.server.members" :key="m.physical_device_id">
                <b>{{ m.device_name }}</b>: {{ memberValue(m) }}
              </li>
            </ul>
          </details>
        </div>
        <div v-if="row.error || inputError(row)" class="row-error" role="alert" data-testid="stack-vlan-error">{{ row.error ?? inputError(row) }}</div>
      </div>

      <div class="add-row">
        <SearchableSelect
          v-model="pickedVlanId"
          :options="pickOptions"
          placeholder="— VLAN для общей настройки —"
          :empty-text="available.length ? 'Все доступные VLAN уже добавлены' : 'Нет VLAN, которые можно назначить всем устройствам стека'"
        />
        <button type="button" class="btn btn-secondary" :disabled="!pickedVlanId" data-testid="stack-vlan-add" @click="addRow">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          VLAN
        </button>
      </div>
    </template>

    <StackVlanRemoveDialog
      v-if="removing"
      :vlan-label="removing.label"
      :stack-name="stackName"
      :member-count="memberCount"
      :busy="removeBusy"
      :error="removeError"
      @confirm="confirmRemove"
      @cancel="removing = null"
    />
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
  gap: 8px;
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
  margin: 0;
  padding: 4px 0;
}
.form-error {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 8px 10px;
  font-size: 12px;
}
.vlan-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--border);
}
.vlan-row {
  display: grid;
  grid-template-columns: 1.2fr 1.1fr 0.7fr auto auto auto;
  align-items: center;
  gap: 8px;
}
.vlan-label {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vlan-row input[type='text'],
.vlan-row input[type='number'] {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
}
.col-mgmt {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.status-line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  font-size: 11.5px;
}
.status-ok {
  color: var(--status-ok);
}
.status-warn {
  color: var(--status-warn);
}
.status-new {
  color: var(--ink-muted);
}
.by-device {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.by-device summary {
  cursor: pointer;
}
.by-device ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.row-error {
  font-size: 11.5px;
  color: var(--status-crit);
}
.add-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  align-items: center;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 700px) {
  .vlan-row {
    grid-template-columns: 1fr;
  }
}
</style>
