<script setup lang="ts">
// Панель «Группы портов» блока «Порты / интерфейсы»: список групп, окно создания/правки группы и
// окно удаления с выбором — оставить значения в портах или стереть.
//
// Группа задаёт один раз режим порта + VLAN, общий IP-адрес и открытые порты для всех своих портов
// (правка формы устройства, п.4). Компонент сам ничего не сохраняет и не обращается к API: любое
// изменение он отдаёт родителю событием change одним объектом { rows, groups } — состав портов и
// значения в них меняются согласованно вместе с группой (см. utils/interfaceGroups.ts).
import { computed, ref } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { vlanLabel } from '../utils/vlan'
import {
  applyGroupsToRows,
  describeGroup,
  emptyGroup,
  eraseGroupValues,
  managedFields,
  memberIndices,
  setGroupMembers,
  validateInterfaceGroups,
} from '../utils/interfaceGroups'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SearchableSelect from './SearchableSelect.vue'

const props = withDefaults(
  defineProps<{
    rows: InterfaceDraftRow[]
    groups: InterfaceGroupDraft[]
    vlanOptions: VLANDefinition[]
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    // Индексы портов, отмеченных галочками в таблице: новая группа предлагает их как свой состав.
    selectedIndices?: number[]
  }>(),
  { protocolPortCatalog: () => [], selectedIndices: () => [] },
)
const emit = defineEmits<{ change: [payload: { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[] }] }>()
const { notify } = useToast()

// --- Окно создания/правки ---------------------------------------------------------------------
// draft — рабочая копия группы; members — индексы её портов (чисто UI-состояние окна до «Сохранить»).
const draft = ref<InterfaceGroupDraft | null>(null)
const draftIsNew = ref(false)
const members = ref<Set<number>>(new Set())
const { onOverlayPointerDown: onEditPointerDown, onOverlayClick: onEditClick } = useOverlayDismiss(closeEdit)

function openCreate() {
  draft.value = emptyGroup()
  draftIsNew.value = true
  members.value = new Set(props.selectedIndices.filter((i) => i < props.rows.length))
}

function openEdit(group: InterfaceGroupDraft) {
  draft.value = { ...group, vlan_ids: [...group.vlan_ids], open_ports: group.open_ports.map((p) => ({ ...p })) }
  draftIsNew.value = false
  members.value = new Set(memberIndices(props.rows, group.key))
}

function closeEdit() {
  draft.value = null
}

function toggleMember(index: number, checked: boolean) {
  const next = new Set(members.value)
  if (checked) next.add(index)
  else next.delete(index)
  members.value = next
}

/** Порт другой группы можно забрать в эту (он перейдёт в неё), но об этом стоит предупредить. */
function otherGroupName(index: number): string | null {
  const key = props.rows[index]?.group_key
  if (!key || key === draft.value?.key) return null
  return props.groups.find((g) => g.key === key)?.name ?? null
}

function setMode(mode: '' | 'access' | 'trunk') {
  if (!draft.value) return
  // Смена режима на access оставляет не более одного VLAN (тот же инвариант, что у порта).
  draft.value = { ...draft.value, vlan_mode: mode, vlan_ids: mode === 'access' ? draft.value.vlan_ids.slice(0, 1) : mode === '' ? [] : draft.value.vlan_ids }
}

function toggleVlan(vlanId: string, checked: boolean) {
  if (!draft.value) return
  const ids = new Set(draft.value.vlan_ids)
  if (checked) ids.add(vlanId)
  else ids.delete(vlanId)
  draft.value = { ...draft.value, vlan_ids: [...ids] }
}

const vlanSelectOptions = computed(() => props.vlanOptions.map((v) => ({ value: v.id, label: vlanLabel(v) })))

function saveDraft() {
  const group = draft.value
  if (!group) return
  const others = props.groups.filter((g) => g.key !== group.key)
  const error = validateInterfaceGroups([...others, group])
  if (error) {
    notify(error, 'error')
    return
  }
  const normalized: InterfaceGroupDraft = { ...group, name: group.name.trim() }
  const groups = draftIsNew.value ? [...props.groups, normalized] : props.groups.map((g) => (g.key === normalized.key ? normalized : g))
  // Состав группы → значения группы записываются в каждый её порт.
  const rows = applyGroupsToRows(setGroupMembers(props.rows, normalized.key, members.value), groups)
  emit('change', { rows, groups })
  closeEdit()
}

// --- Окно удаления ----------------------------------------------------------------------------
const deleting = ref<InterfaceGroupDraft | null>(null)
const { onOverlayPointerDown: onDeletePointerDown, onOverlayClick: onDeleteClick } = useOverlayDismiss(() => (deleting.value = null))

const deletingMembers = computed(() => (deleting.value ? memberIndices(props.rows, deleting.value.key).length : 0))
const deletingManaged = computed(() => managedFields(deleting.value ?? undefined))
const deletingManagedText = computed(() => {
  const m = deletingManaged.value
  return [m.vlan && 'режим порта и VLAN', m.ip && 'IP-адрес', m.openPorts && 'открытые порты'].filter(Boolean).join(', ')
})

function requestDelete(group: InterfaceGroupDraft) {
  // Нечего сохранять или стирать (нет портов или группа ничего не задаёт) — вопрос не нужен.
  const m = managedFields(group)
  if (!memberIndices(props.rows, group.key).length || (!m.vlan && !m.ip && !m.openPorts)) {
    confirmDelete(group, 'keep')
    return
  }
  deleting.value = group
}

/** keep — значения остаются в портах (по умолчанию, уже записаны в строки); erase — значения тех
 * параметров, которыми управляла группа, стираются у всех её портов. Группа удаляется в обоих
 * случаях, порты остаются без группы. */
function confirmDelete(group: InterfaceGroupDraft, choice: 'keep' | 'erase') {
  const rows = props.rows.map((row) => {
    if (row.group_key !== group.key) return row
    const cleaned = choice === 'erase' ? eraseGroupValues(row, group) : row
    return { ...cleaned, group_key: '' }
  })
  emit('change', { rows, groups: props.groups.filter((g) => g.key !== group.key) })
  deleting.value = null
}

function vlanTitle(vlanId: string): string {
  const v = props.vlanOptions.find((x) => x.id === vlanId)
  return v ? vlanLabel(v) : vlanId
}

function portTitle(catalogId: string): string {
  const e = props.protocolPortCatalog.find((x) => x.id === catalogId)
  return e ? `${e.port}/${e.protocol_type}` : catalogId
}

function summary(group: InterfaceGroupDraft): string {
  return describeGroup(group, vlanTitle, portTitle)
}
</script>

<template>
  <div class="groups-panel">
    <div class="groups-head">
      <div class="groups-title">
        <b>Группы портов</b>
        <span class="hint">Режим порта, IP-адрес и открытые порты задаются один раз для всех портов группы.</span>
      </div>
      <button type="button" class="btn btn-secondary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Группа
      </button>
    </div>

    <div v-if="!groups.length" class="empty">Групп нет. Отметьте порты в таблице ниже и нажмите «Группа».</div>
    <ul v-else class="group-list">
      <li v-for="group in groups" :key="group.key" class="group-item">
        <div class="group-main">
          <b class="group-name">{{ group.name || 'Без названия' }}</b>
          <span class="group-count">Портов: {{ memberIndices(rows, group.key).length }}</span>
          <span class="group-summary">{{ summary(group) }}</span>
        </div>
        <button type="button" class="icon-btn" aria-label="Изменить группу" title="Изменить группу" @click="openEdit(group)">
          <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
        </button>
        <button type="button" class="icon-btn danger" aria-label="Удалить группу" title="Удалить группу" @click="requestDelete(group)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </li>
    </ul>
  </div>

  <div v-if="draft" class="overlay" @mousedown="onEditPointerDown" @click="onEditClick">
    <div class="group-modal card" role="dialog" aria-modal="true" :aria-label="draftIsNew ? 'Новая группа портов' : 'Группа портов'">
      <div class="group-modal-head">
        <h3>{{ draftIsNew ? 'Новая группа портов' : 'Группа портов' }}</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="closeEdit">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <label class="field">
        <span>Наименование *</span>
        <input v-model="draft.name" type="text" maxlength="100" placeholder="напр. Серверные порты" />
      </label>

      <fieldset class="group-section">
        <legend>Порты группы</legend>
        <div v-if="!rows.length" class="empty">В списке нет портов.</div>
        <label v-for="(row, i) in rows" :key="row.id ?? i" class="member-check">
          <input type="checkbox" :checked="members.has(i)" @change="toggleMember(i, ($event.target as HTMLInputElement).checked)" />
          <span>{{ row.name || `#${i + 1}` }}</span>
          <span v-if="otherGroupName(i)" class="member-note">сейчас в группе «{{ otherGroupName(i) }}» — перейдёт в эту</span>
        </label>
      </fieldset>

      <fieldset class="group-section">
        <legend>Общие параметры (задаются только отмеченные)</legend>

        <div class="param">
          <div class="param-head"><b>Режим порта</b></div>
          <div class="mode-row">
            <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === ''" @change="setMode('')" /> Не задавать</label>
            <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === 'access'" @change="setMode('access')" /> Access</label>
            <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === 'trunk'" @change="setMode('trunk')" /> Trunk</label>
          </div>
          <template v-if="draft.vlan_mode === 'access'">
            <SearchableSelect
              :model-value="draft.vlan_ids[0] ?? ''"
              :options="vlanSelectOptions"
              placeholder="— VLAN не выбран —"
              @update:model-value="(v) => (draft = { ...draft!, vlan_ids: v ? [v] : [] })"
            />
          </template>
          <div v-else-if="draft.vlan_mode === 'trunk'" class="vlan-checks">
            <span v-if="!vlanOptions.length" class="empty">Для типа устройства VLAN не назначены</span>
            <label v-for="v in vlanOptions" :key="v.id" class="vlan-check">
              <input type="checkbox" :checked="draft.vlan_ids.includes(v.id)" @change="toggleVlan(v.id, ($event.target as HTMLInputElement).checked)" />
              {{ vlanLabel(v) }}
            </label>
          </div>
        </div>

        <div class="param">
          <div class="param-head"><b>Общий IP-адрес</b><span class="hint">один адрес на все порты группы; заменит IP-адреса этих портов</span></div>
          <div class="ip-row">
            <input v-model="draft.ip_address" type="text" placeholder="IP-адрес (пусто — не задавать)" aria-label="Общий IP-адрес группы" />
            <!-- Не v-model: на type="number" он записал бы в черновик число, а prefix_length везде в форме —
               строка (как у IP порта), и валидатор префикса вызывает у значения строковые методы. -->
          <input
            :value="draft.prefix_length"
            type="number"
            min="0"
            max="32"
            placeholder="Префикс"
            aria-label="Префикс общего IP-адреса"
            @input="draft = { ...draft!, prefix_length: ($event.target as HTMLInputElement).value }"
          />
          </div>
        </div>

        <div class="param">
          <label class="param-head manage-check">
            <input v-model="draft.manage_open_ports" type="checkbox" />
            <b>Задать открытые порты / протоколы</b>
            <span class="hint">заменит открытые порты этих портов</span>
          </label>
          <OpenPortListEditor v-if="draft.manage_open_ports" v-model="draft.open_ports" :catalog-entries="protocolPortCatalog" />
        </div>
      </fieldset>

      <div class="group-modal-actions">
        <button type="button" class="btn btn-secondary" @click="closeEdit">Отмена</button>
        <button type="button" class="btn btn-primary" @click="saveDraft">{{ draftIsNew ? 'Создать группу' : 'Применить' }}</button>
      </div>
    </div>
  </div>

  <div v-if="deleting" class="overlay" @mousedown="onDeletePointerDown" @click="onDeleteClick">
    <div class="delete-modal card" role="dialog" aria-modal="true" aria-label="Удаление группы портов">
      <div class="group-modal-head">
        <h3>Удалить группу «{{ deleting.name }}»?</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="deleting = null">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="delete-desc">
        В группе портов: {{ deletingMembers }}. Группа задавала: {{ deletingManagedText }}. Что сделать со значениями в этих портах?
      </p>
      <div class="delete-actions">
        <button type="button" class="btn btn-primary" @click="confirmDelete(deleting, 'keep')">Оставить значения в портах</button>
        <button type="button" class="btn btn-secondary danger-btn" @click="confirmDelete(deleting, 'erase')">Стереть значения</button>
        <button type="button" class="btn btn-secondary" @click="deleting = null">Отмена</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.groups-panel {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.groups-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.groups-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.groups-title b {
  font-size: 12px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.group-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.group-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--r-s, 6px);
}
.group-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}
.group-name {
  font-size: 12.5px;
}
.group-count {
  font-size: 11px;
  color: var(--ink-muted);
}
.group-summary {
  flex-basis: 100%;
  font-size: 11.5px;
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 70;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.group-modal,
.delete-modal {
  width: 100%;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-modal {
  max-width: 640px;
}
.delete-modal {
  max-width: 440px;
}
.group-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.group-modal-head h3 {
  font-family: var(--font-display);
  font-size: 14.5px;
  margin: 0;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.field input {
  width: 100%;
}
.group-section {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 8px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.group-section legend {
  font-size: 11px;
  color: var(--ink-muted);
  padding: 0 4px;
}
.member-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
.member-note {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.param {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  font-size: 12px;
}
.manage-check {
  align-items: center;
  cursor: pointer;
}
.mode-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.radio-inline {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
}
.vlan-checks {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow-y: auto;
}
.vlan-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}
.ip-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px;
  gap: 8px;
}
.group-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.delete-desc {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0;
}
.delete-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.delete-actions .btn {
  width: 100%;
  justify-content: center;
}
.danger-btn {
  color: var(--danger, #d64545);
}
</style>
