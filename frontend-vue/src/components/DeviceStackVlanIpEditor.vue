<script setup lang="ts">
// Общие IP-адрес и маска VLAN для всех устройств стека (кластера): вводятся один раз и записываются каждому участнику.
//
// Источник истины — IP/префикс в «VLAN устройства» каждого участника (PhysicalDeviceVLAN), отдельного «общего»
// значения нет: блок показывает, как VLAN настроен на участниках, и по кнопке «Применить ко всем» одним запросом
// (PUT /device-stacks/{id}/vlans/{vlan_id}) приводит всех к введённой паре. Если адрес потом поправили на одном
// устройстве (форма устройства), здесь это видно как «Адреса различаются» — молча ничего не перезаписывается.
// Недостающие назначения VLAN создаются; флаг «Управление» и описание у существующих не меняются.
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { DeviceStackVlans, StackVlanOption, StackVlanRow } from '../api/types'
import { useToast } from '../composables/useToast'
import { matchesSharedValue, sharedIpPayload, stackVlanStatus, validateSharedIp } from '../utils/stackVlans'
import SearchableSelect from './SearchableSelect.vue'

const props = defineProps<{
  stackId: string
  memberCount: number
  /** Меняется при любой перезагрузке состава стека (добавили/убрали участника, сохранили устройство) — блок перечитывает VLAN. */
  reloadToken: number
}>()
const emit = defineEmits<{ applied: [] }>()
const { notify } = useToast()

/** Строка блока: server — состояние на участниках (null у только что добавленной в форме), ip/prefix — вводимые значения. */
interface DraftRow {
  vlanId: string
  label: string
  server: StackVlanRow | null
  ip: string
  prefix: string
  busy: boolean
  error: string | null
}

const rows = ref<DraftRow[]>([])
const available = ref<StackVlanOption[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const pickedVlanId = ref('')

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
    busy: false,
    error: null,
  }
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const res = await api.get<DeviceStackVlans>(`/device-stacks/${props.stackId}/vlans`)
    rows.value = (res.items ?? []).map(draftFromServer)
    available.value = res.available ?? []
    pickedVlanId.value = ''
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Не удалось загрузить VLAN стека'
  } finally {
    loading.value = false
  }
}

watch(() => [props.stackId, props.reloadToken], load, { immediate: true })

// Ещё не добавленные в блок VLAN, которые можно назначить каждому участнику (список приходит с сервера).
const pickOptions = computed(() => {
  const taken = new Set(rows.value.map((r) => r.vlanId))
  return available.value.filter((v) => !taken.has(v.vlan_id)).map((v) => ({ value: v.vlan_id, label: vlanText(v.vlan_number, v.vlan_name) }))
})

function addRow() {
  const option = available.value.find((v) => v.vlan_id === pickedVlanId.value)
  if (!option) return
  rows.value.push({ vlanId: option.vlan_id, label: vlanText(option.vlan_number, option.vlan_name), server: null, ip: '', prefix: '', busy: false, error: null })
  pickedVlanId.value = ''
}

function removeDraft(row: DraftRow) {
  rows.value = rows.value.filter((r) => r !== row)
}

function inputError(row: DraftRow): string | null {
  return validateSharedIp(row.ip, row.prefix)
}

function canApply(row: DraftRow): boolean {
  return !row.busy && inputError(row) === null && !matchesSharedValue(row.server, row.ip, row.prefix)
}

/** Подставляет свежее состояние сервера: применённая строка пересоздаётся целиком, остальные сохраняют вводимые значения. */
function mergeServerState(res: DeviceStackVlans, appliedVlanId: string) {
  const byId = new Map((res.items ?? []).map((item) => [item.vlan_id, item]))
  rows.value = rows.value.map((r) => {
    const fresh = byId.get(r.vlanId)
    if (r.vlanId === appliedVlanId && fresh) return draftFromServer(fresh)
    return fresh ? { ...r, server: fresh } : r
  })
  available.value = res.available ?? []
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
    const res = await api.put<DeviceStackVlans>(`/device-stacks/${props.stackId}/vlans/${row.vlanId}`, sharedIpPayload(row.ip, row.prefix))
    mergeServerState(res, row.vlanId)
    notify(`VLAN ${row.label}: настройка применена ко всем устройствам стека`, 'success')
    emit('applied')
  } catch (err) {
    row.error = err instanceof Error ? err.message : 'Не удалось применить адрес ко всем устройствам стека'
  } finally {
    row.busy = false
  }
}

function memberValue(m: { assigned: boolean; ip_address: string | null; prefix_length: number | null }): string {
  if (!m.assigned) return 'VLAN не назначен'
  if (!m.ip_address) return 'адрес не задан'
  return m.prefix_length === null ? m.ip_address : `${m.ip_address}/${m.prefix_length}`
}
</script>

<template>
  <div class="nested-editor field-wide" data-testid="stack-vlan-ip-editor">
    <div class="nested-head">
      <b>Общие IP-адреса VLAN стека</b>
      <span class="hint">
        Один IP-адрес и префикс (маска) для VLAN записываются каждому устройству стека — например, общий адрес кластера. Недостающие
        назначения VLAN создаются, флаг «Управление» и описание не меняются.
      </span>
    </div>

    <p v-if="memberCount === 0" class="empty">Добавьте устройства в стек, чтобы задать им общий IP-адрес VLAN.</p>
    <template v-else>
      <div v-if="loadError" class="form-error" role="alert">{{ loadError }}</div>
      <p v-else-if="loading && !rows.length" class="empty">Загрузка VLAN стека…</p>
      <p v-else-if="!rows.length" class="empty">VLAN устройствам стека не назначены. Добавьте VLAN ниже.</p>

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
          <button type="button" class="btn btn-secondary" :disabled="!canApply(row)" data-testid="stack-vlan-apply" @click="apply(row)">
            Применить ко всем
          </button>
          <button
            v-if="!row.server"
            type="button"
            class="icon-btn danger"
            aria-label="Убрать строку"
            data-testid="stack-vlan-remove-draft"
            @click="removeDraft(row)"
          >
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
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
          placeholder="— VLAN для общего адреса —"
          :empty-text="available.length ? 'Все доступные VLAN уже добавлены' : 'Нет VLAN, которые можно назначить всем устройствам стека'"
        />
        <button type="button" class="btn btn-secondary" :disabled="!pickedVlanId" data-testid="stack-vlan-add" @click="addRow">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          VLAN
        </button>
      </div>
    </template>
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
  grid-template-columns: 1.3fr 1.2fr 0.7fr auto auto;
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
.vlan-row input {
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
