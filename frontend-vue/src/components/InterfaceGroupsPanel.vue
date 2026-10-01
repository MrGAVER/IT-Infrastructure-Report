<script setup lang="ts">
// Панель «Группы портов» блока «Порты / интерфейсы»: список групп, окно создания/правки группы и
// окно удаления с выбором — оставить значения в портах или стереть.
//
// Группа задаёт один раз режим порта + VLAN, общий IP-адрес (с префиксом и назначением) и открытые порты для всех своих портов
// (правка формы устройства, п.4). Компонент сам ничего не сохраняет и не обращается к API: любое
// изменение он отдаёт родителю событием change одним объектом { rows, groups } — состав портов и
// значения в них меняются согласованно вместе с группой (см. utils/interfaceGroups.ts).
import { computed, ref, watch } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { vlanLabel } from '../utils/vlan'
import {
  applyGroupsToRows,
  copyValuesFromRow,
  copyableFields,
  describeGroup,
  emptyGroup,
  eraseGroupValues,
  managedFields,
  memberIndices,
  setGroupMembers,
  validateInterfaceGroups,
  type ManagedFields,
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
  resetCopy()
}

function openEdit(group: InterfaceGroupDraft) {
  draft.value = { ...group, vlan_ids: [...group.vlan_ids], open_ports: group.open_ports.map((p) => ({ ...p })) }
  draftIsNew.value = false
  members.value = new Set(memberIndices(props.rows, group.key))
  resetCopy()
}

function closeEdit() {
  draft.value = null
}

// --- Копирование значений с порта -------------------------------------------------------------
// Порт-источник выбирается среди портов этого устройства (строки редактора). Копируются только
// отмеченные параметры, у которых на порту есть значение (utils/interfaceGroups.ts:copyableFields);
// копия попадает в черновик группы и применяется к портам, как и любое другое значение, при
// сохранении группы.
const copySource = ref('')
const copyWhat = ref<ManagedFields>({ vlan: false, ip: false, openPorts: false })

const copyPortOptions = computed(() => props.rows.map((row, i) => ({ value: String(i), label: row.name || `#${i + 1}` })))
const copyRow = computed(() => (copySource.value === '' ? undefined : props.rows[Number(copySource.value)]))
const copyAvailable = computed(() => (copyRow.value ? copyableFields(copyRow.value) : { vlan: false, ip: false, openPorts: false }))
const copyNothingAvailable = computed(() => !!copyRow.value && !copyAvailable.value.vlan && !copyAvailable.value.ip && !copyAvailable.value.openPorts)
const canCopy = computed(() => (copyWhat.value.vlan && copyAvailable.value.vlan) || (copyWhat.value.ip && copyAvailable.value.ip) || (copyWhat.value.openPorts && copyAvailable.value.openPorts))

function resetCopy() {
  copySource.value = ''
  copyWhat.value = { vlan: false, ip: false, openPorts: false }
}

// Выбрали порт — сразу отмечаем всё, что с него можно скопировать.
watch(copySource, () => {
  copyWhat.value = { ...copyAvailable.value }
})

function copyFromPort() {
  const row = copyRow.value
  if (!draft.value || !row || !canCopy.value) return
  draft.value = copyValuesFromRow(draft.value, row, copyWhat.value)
  const label = row.name || `#${Number(copySource.value) + 1}`
  const manyIps = copyWhat.value.ip && row.ips.filter((ip) => ip.ip_address.trim() !== '').length > 1
  notify(manyIps ? `Значения скопированы с порта «${label}». У порта несколько IP-адресов — скопирован первый.` : `Значения скопированы с порта «${label}».`, 'success')
  resetCopy()
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
        <span class="hint">Режим порта, IP-адрес (с назначением) и открытые порты задаются один раз для всех портов группы.</span>
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
      <div class="modal-head">
        <h2>{{ draftIsNew ? 'Новая группа портов' : 'Группа портов' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="closeEdit">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div class="group-body">
        <label class="field">
          <span>Наименование *</span>
          <input v-model="draft.name" type="text" maxlength="100" placeholder="напр. Серверные порты" />
        </label>

        <section class="nested-editor">
          <div class="nested-head">
            <b>Порты группы</b>
            <span class="hint">К отмеченным портам применяются общие параметры ниже.</span>
          </div>
          <div v-if="!rows.length" class="empty">В списке нет портов.</div>
          <div v-else class="member-grid">
            <label v-for="(row, i) in rows" :key="row.id ?? i" class="member-check">
              <input type="checkbox" :checked="members.has(i)" @change="toggleMember(i, ($event.target as HTMLInputElement).checked)" />
              <span class="member-name">{{ row.name || `#${i + 1}` }}</span>
              <span v-if="otherGroupName(i)" class="member-note">перейдёт из группы «{{ otherGroupName(i) }}»</span>
            </label>
          </div>
        </section>

        <section class="nested-editor">
          <div class="nested-head">
            <b>Общие параметры</b>
            <span class="hint">Группа управляет только теми параметрами, которые заданы ниже.</span>
          </div>

          <div class="copy-block">
            <div class="param-head"><b>Скопировать значения с порта</b><span class="hint">заполнит параметры ниже значениями выбранного порта</span></div>
            <div class="copy-row">
              <SearchableSelect v-model="copySource" :options="copyPortOptions" placeholder="— порт устройства —" />
              <button type="button" class="btn btn-secondary" :disabled="!canCopy" @click="copyFromPort">Скопировать</button>
            </div>
            <div v-if="copyRow" class="copy-what">
              <label class="check-inline" :class="{ disabled: !copyAvailable.vlan }">
                <input v-model="copyWhat.vlan" type="checkbox" :disabled="!copyAvailable.vlan" /> Режим порта и VLAN
              </label>
              <label class="check-inline" :class="{ disabled: !copyAvailable.ip }">
                <input v-model="copyWhat.ip" type="checkbox" :disabled="!copyAvailable.ip" /> IP-адрес
              </label>
              <label class="check-inline" :class="{ disabled: !copyAvailable.openPorts }">
                <input v-model="copyWhat.openPorts" type="checkbox" :disabled="!copyAvailable.openPorts" /> Открытые порты
              </label>
              <span v-if="copyNothingAvailable" class="hint">У порта нет значений, которые можно скопировать.</span>
            </div>
          </div>

          <div class="param vlan-param">
            <div class="param-head"><b>Режим порта</b></div>
            <div class="mode-row">
              <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === ''" @change="setMode('')" /> Не задавать</label>
              <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === 'access'" @change="setMode('access')" /> Access</label>
              <label class="radio-inline"><input type="radio" name="group-mode" :checked="draft.vlan_mode === 'trunk'" @change="setMode('trunk')" /> Trunk</label>
            </div>
            <SearchableSelect
              v-if="draft.vlan_mode === 'access'"
              :model-value="draft.vlan_ids[0] ?? ''"
              :options="vlanSelectOptions"
              placeholder="— VLAN не выбран —"
              @update:model-value="(v) => (draft = { ...draft!, vlan_ids: v ? [v] : [] })"
            />
            <div v-else-if="draft.vlan_mode === 'trunk'" class="vlan-checks">
              <span v-if="!vlanOptions.length" class="empty">Для типа устройства VLAN не назначены</span>
              <label v-for="v in vlanOptions" :key="v.id" class="check-inline">
                <input type="checkbox" :checked="draft.vlan_ids.includes(v.id)" @change="toggleVlan(v.id, ($event.target as HTMLInputElement).checked)" />
                {{ vlanLabel(v) }}
              </label>
            </div>
          </div>

          <div class="param">
            <div class="param-head"><b>Общий IP-адрес</b><span class="hint">один адрес, префикс и назначение на все порты группы; заменят IP-адреса этих портов (пустое назначение очистит назначение у портов)</span></div>
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
              <input
                v-model="draft.ip_purpose"
                type="text"
                maxlength="255"
                placeholder="Назначение"
                aria-label="Назначение общего IP-адреса группы"
                :disabled="!draft.ip_address.trim()"
                :title="draft.ip_address.trim() ? undefined : 'Сначала укажите общий IP-адрес'"
              />
            </div>
          </div>

          <div class="param ports-param">
            <label class="param-head manage-check">
              <input v-model="draft.manage_open_ports" type="checkbox" />
              <b>Задать открытые порты / протоколы</b>
              <span class="hint">заменит открытые порты этих портов</span>
            </label>
            <OpenPortListEditor v-if="draft.manage_open_ports" v-model="draft.open_ports" :catalog-entries="protocolPortCatalog" />
          </div>
        </section>
      </div>

      <div class="modal-foot group-modal-actions">
        <button type="button" class="btn btn-secondary" @click="closeEdit">Отмена</button>
        <button type="button" class="btn btn-primary" @click="saveDraft">{{ draftIsNew ? 'Создать группу' : 'Применить' }}</button>
      </div>
    </div>
  </div>

  <div v-if="deleting" class="overlay" @mousedown="onDeletePointerDown" @click="onDeleteClick">
    <div class="delete-modal card" role="dialog" aria-modal="true" aria-label="Удаление группы портов">
      <div class="modal-head">
        <h2>Удалить группу «{{ deleting.name }}»?</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="deleting = null">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="delete-desc">
        В группе портов: {{ deletingMembers }}. Группа задавала: {{ deletingManagedText }}. Что сделать со значениями в этих портах?
      </p>
      <div class="delete-actions">
        <button type="button" class="btn btn-primary" @click="confirmDelete(deleting, 'keep')">Оставить значения в портах</button>
        <button type="button" class="btn btn-danger danger-btn" @click="confirmDelete(deleting, 'erase')">Стереть значения</button>
        <button type="button" class="btn btn-secondary" @click="deleting = null">Отмена</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Внешний вид приведён к остальным окнам приложения (QuickAddModal, DeviceInterfacesEditor):
   в приложении нет глобальных стилей для полей ввода — каждый компонент красит их сам, поэтому
   необъявленные здесь input/радио/чекбоксы оставались нативными (светлыми). */
.groups-panel {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
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
  padding: 8px 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
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
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

/* --- модальные окна: та же база, что у QuickAddModal.vue --- */
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
  padding: 20px 22px 18px;
}
.group-modal {
  max-width: 680px;
}
.delete-modal {
  max-width: 440px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.group-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* --- поля: значения те же, что у .field в QuickAddModal.vue --- */
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
  min-width: 0;
}
.group-modal input[type='text'],
.group-modal input[type='number'] {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.group-modal input::placeholder {
  color: var(--ink-muted);
}

/* --- вложенные блоки: как .nested-editor в DeviceInterfacesEditor.vue --- */
.nested-editor {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.nested-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nested-head b {
  font-size: 12.5px;
}

.member-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 6px 14px;
  max-height: 200px;
  overflow-y: auto;
}
.member-check {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.member-name {
  min-width: 0;
  overflow-wrap: anywhere;
}
.member-note {
  flex-basis: 100%;
  padding-left: 20px;
  font-size: 10.5px;
  color: var(--status-warn);
}

.param {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param + .param,
.copy-block + .param {
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.param-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  font-size: 11.5px;
}
.param-head b {
  font-size: 11.5px;
}
.manage-check {
  align-items: center;
  cursor: pointer;
}

/* радио и чекбоксы — как .radio-inline / .vlan-check в DeviceInterfacesEditor.vue */
.mode-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}
.radio-inline,
.check-inline {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.check-inline.disabled {
  color: var(--ink-muted);
  cursor: not-allowed;
}
.radio-inline input,
.check-inline input,
.member-check input,
.manage-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
  margin: 0;
  flex-shrink: 0;
}
.vlan-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  max-height: 180px;
  overflow-y: auto;
}

.ip-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px minmax(0, 1fr);
  gap: 8px;
}

/* копирование значений с порта */
.copy-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.copy-row {
  display: flex;
  align-items: stretch;
  gap: 6px;
}
.copy-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.copy-what {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
}

.delete-desc {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0 0 14px;
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
.btn-danger {
  background: transparent;
  border: 1px solid var(--status-crit);
  color: var(--status-crit);
}
.btn-danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 520px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
