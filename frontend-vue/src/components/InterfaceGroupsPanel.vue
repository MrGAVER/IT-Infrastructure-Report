<script setup lang="ts">
// Панель «Группы портов» блока «Порты / интерфейсы»: список групп, окно создания/правки группы (GroupEditModal.vue) и
// окно удаления с выбором — оставить значения в портах или стереть (GroupDeleteModal.vue).
//
// Группа задаёт один раз режим порта + VLAN, общий IP-адрес (с префиксом и назначением), открытые порты и подинтерфейсы для всех
// своих портов (правка формы устройства, п.4). Компонент сам ничего не сохраняет и не обращается к API: любое
// изменение он отдаёт родителю событием change одним объектом { rows, groups } — состав портов и
// значения в них меняются согласованно вместе с группой (см. utils/interfaceGroups.ts).
import { ref } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { normalizeGroupSubinterfaces } from '../utils/groupDraftEdit'
import { vlanLabel } from '../utils/vlan'
import { sortOpenPortRows } from '../utils/openPorts'
import { applyGroupsToRows, describeGroup, emptyGroup, eraseGroupValues, managedFields, memberIndices, setGroupMembers, validateInterfaceGroups } from '../utils/interfaceGroups'
import GroupDeleteModal from './GroupDeleteModal.vue'
import GroupEditModal from './GroupEditModal.vue'

const props = withDefaults(
  defineProps<{
    rows: InterfaceDraftRow[]
    groups: InterfaceGroupDraft[]
    vlanOptions: VLANDefinition[]
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    // Индексы портов, отмеченных галочками в таблице: новая группа предлагает их как свой состав.
    selectedIndices?: number[]
    // Порог сворачивания списка открытых портов группы (общий порог из «Настроек»); не передан — без сворачивания.
    collapseAfter?: number
  }>(),
  { protocolPortCatalog: () => [], selectedIndices: () => [] },
)
const emit = defineEmits<{ change: [payload: { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[] }] }>()
const { notify } = useToast()

// --- Окно создания/правки ---------------------------------------------------------------------
// Сеанс правки: исходная группа, признак «новая» и состав портов при открытии (чисто UI-состояние окна до «Сохранить»).
interface EditSession {
  group: InterfaceGroupDraft
  isNew: boolean
  members: Set<number>
}
const editing = ref<EditSession | null>(null)

function openCreate() {
  editing.value = { group: emptyGroup(), isNew: true, members: new Set(props.selectedIndices.filter((i) => i < props.rows.length)) }
}

function openEdit(group: InterfaceGroupDraft) {
  editing.value = { group, isNew: false, members: new Set(memberIndices(props.rows, group.key)) }
}

function saveGroup({ group, members }: { group: InterfaceGroupDraft; members: ReadonlySet<number> }) {
  const session = editing.value
  if (!session) return
  const others = props.groups.filter((g) => g.key !== group.key)
  const error = validateInterfaceGroups([...others, group], props.protocolPortCatalog, new Set(props.vlanOptions.map((v) => v.id)))
  if (error) {
    notify(error, 'error')
    return
  }
  // Окно группы закрывается — это «заново открытая» форма: открытые порты группы встают по возрастанию
  // номера порта (так же они придут и в порты-участники, и при следующем открытии окна).
  const normalized: InterfaceGroupDraft = {
    ...group,
    name: group.name.trim(),
    open_ports: sortOpenPortRows(group.open_ports, props.protocolPortCatalog),
    subinterfaces: normalizeGroupSubinterfaces(group.subinterfaces ?? [], props.vlanOptions, props.protocolPortCatalog),
  }
  const groups = session.isNew ? [...props.groups, normalized] : props.groups.map((g) => (g.key === normalized.key ? normalized : g))
  // Состав группы → значения группы записываются в каждый её порт.
  const rows = applyGroupsToRows(setGroupMembers(props.rows, normalized.key, members), groups, props.vlanOptions)
  emit('change', { rows, groups })
  editing.value = null
}

// --- Окно удаления ----------------------------------------------------------------------------
const deleting = ref<InterfaceGroupDraft | null>(null)

function requestDelete(group: InterfaceGroupDraft) {
  // Нечего сохранять или стирать (нет портов или группа ничего не задаёт) — вопрос не нужен.
  const m = managedFields(group)
  if (!memberIndices(props.rows, group.key).length || (!m.vlan && !m.ip && !m.openPorts && !m.subinterfaces)) {
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

function confirmDeleting(choice: 'keep' | 'erase') {
  if (deleting.value) confirmDelete(deleting.value, choice)
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
        <span class="hint">Режим порта, IP-адрес (с назначением), открытые порты и подинтерфейсы задаются один раз для всех портов группы.</span>
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

  <GroupEditModal
    v-if="editing"
    :group="editing.group"
    :is-new="editing.isNew"
    :members="editing.members"
    :rows="rows"
    :groups="groups"
    :vlan-options="vlanOptions"
    :protocol-port-catalog="protocolPortCatalog"
    :collapse-after="collapseAfter"
    @close="editing = null"
    @save="saveGroup"
  />

  <GroupDeleteModal v-if="deleting" :group="deleting" :members-count="memberIndices(rows, deleting.key).length" @close="deleting = null" @confirm="confirmDeleting" />
</template>

<style scoped src="../styles/groupPanelShared.css"></style>
<style scoped>
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
</style>
