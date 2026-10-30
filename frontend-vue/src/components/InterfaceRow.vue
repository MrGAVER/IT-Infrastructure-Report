<script setup lang="ts">
// Строка таблицы портов и её раскрытая часть: поля порта (имя, тип, MAC, скорость, «Упр.» / «Данные»), сводка «VLAN / IP» с
// индикаторами проблем и кнопка раскрытия; в раскрытой части — описание, блоки VLAN, IP-адресов, подинтерфейсов, подключения и
// открытых портов. Строка ничего не меняет сама: изменение порта уходит событием update (patch), остальные действия — отдельными
// событиями; что с ними делать, решают композиблы редактора (DeviceInterfacesEditor.vue). Корень — фрагмент из двух <tr>, поэтому
// стили строки живут здесь, а не в родителе: scope-атрибут родителя на её элементы не переходит.
import { computed } from 'vue'
import type {
  CatalogItem,
  InterfaceDraftRow,
  InterfaceGroupDraft,
  InterfaceIpDraftRow,
  OpenPortDraftRow,
  PortConflictInfo,
  ProtocolPortCatalogEntry,
  VLANDefinition,
  VlanMode,
} from '../api/types'
import { useGroupLocks } from '../composables/useGroupLocks'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { isAllVlansSelected } from '../utils/allVlans'
import type { ConfigDiffKind, PeerConfigTarget } from '../utils/interfaceConnections'
import { selfPortCandidates, takenPeerIds } from '../utils/interfacePeers'
import { conflictSummary, connectionSummary, duplicatePortsText, staleSubinterfaceText, vlanCellSummary, type ConflictKind } from '../utils/interfaceRowView'
import { duplicatePortNumbers } from '../utils/openPorts'
import { portConfigOf } from '../utils/portConflicts'
import { portVlanOptions } from '../utils/subinterfaces'
import InterfaceConnectionEditor from './InterfaceConnectionEditor.vue'
import InterfaceIpBlock from './InterfaceIpBlock.vue'
import InterfaceOpenPortsBlock from './InterfaceOpenPortsBlock.vue'
import InterfaceSubinterfacesEditor from './InterfaceSubinterfacesEditor.vue'
import InterfaceVlanBlock from './InterfaceVlanBlock.vue'

const props = defineProps<{
  row: InterfaceDraftRow
  /** Номер строки в таблице. */
  index: number
  /** Все порты устройства: нужны для порядка, сводки подключения, списка соседей и получателей копирования открытых портов. */
  rows: InterfaceDraftRow[]
  /** Группы портов устройства: по ним видно, какие поля порта заданы группой и заблокированы. */
  groups: InterfaceGroupDraft[]
  selected: boolean
  expanded: boolean
  /** Выбранный получатель копирования открытых портов — номер порта строкой, '' — не выбран. */
  copyTarget: string
  typeOptions: CatalogItem[]
  speedOptions: CatalogItem[]
  /** VLAN, доступные порту. */
  vlanOptions: VLANDefinition[]
  /** Все известные VLAN (справочник), включая уже недоступные устройству. */
  vlanCatalog: VLANDefinition[]
  /** Идентификаторы VLAN, назначенных устройству: подинтерфейс на другом VLAN считается «висящим». */
  allowedVlanIds: ReadonlySet<string>
  protocolPortCatalog: ProtocolPortCatalogEntry[]
  /** Порог сворачивания длинных списков (из «Настроек»). */
  collapseAfter: number
  /** Расхождение с портом на другом конце подключения. */
  conflict: PortConflictInfo | undefined
  /** Показывать блок «Подключение» (только там, где подключения сохраняются вместе с портами). */
  editConnections: boolean
  deviceId: string | null
  deviceLabel?: string
  /** Порты других устройств, которые эта форма освобождает: их можно выбрать соседом. */
  freedPeerIds: ReadonlySet<string>
  /** Идёт применение конфигурации соседу — кнопки «Применить…» недоступны. */
  applyingPeerConfig: boolean
  /** Счётчик изменений портов соседей: при росте порты соседа перечитываются с сервера. */
  peersVersion: number
}>()
const emit = defineEmits<{
  select: [checked: boolean]
  'toggle-expand': []
  /** Сдвинуть порт на delta позиций (-1 выше, 1 ниже). */
  move: [delta: -1 | 1]
  remove: []
  /** Имя порта изменено: вместе с ним пересчитываются автоимена подинтерфейсов. */
  rename: [name: string]
  update: [patch: Partial<InterfaceDraftRow>]
  'open-conflict': [kind: ConflictKind]
  'set-vlan-mode': [mode: VlanMode]
  'set-access-vlan': [vlanId: string]
  'toggle-all-vlans': [checked: boolean]
  'open-vlan-picker': []
  'set-copy-target': [value: string]
  'apply-copy': []
  'apply-peer-config': [peer: PeerConfigTarget, kinds: ConfigDiffKind[]]
  'apply-config-to-peer': [peer: PeerConfigTarget, kinds: ConfigDiffKind[]]
}>()

const { rowGroup, rowManaged, groupLockNote } = useGroupLocks(() => props.groups)
const group = computed(() => rowGroup(props.row))
const managed = computed(() => rowManaged(props.row))
// Лишнее показывается индикатором на свёрнутой строке — иначе подсвеченную внутри раскрытого блока строку увидит только тот,
// кто его раскроет; сохранение с таким всё равно блокируется (validateInterfaceDraftRows).
const duplicatePorts = computed(() => duplicatePortNumbers(props.row.open_ports, props.protocolPortCatalog))
const staleText = computed(() => staleSubinterfaceText(props.row, props.allowedVlanIds))
// VLAN, из которых выбирается VLAN подинтерфейса порта: выбранные на самом порту (с «Все VLAN» — все VLAN устройства).
const subinterfaceVlanOptions = computed(() => portVlanOptions(props.row, props.vlanOptions))
const takenIds = computed(() => takenPeerIds(props.rows, props.index))
const selfPorts = computed(() => selfPortCandidates(props.rows, props.index))
const lockNote = (managedField: boolean, what: string) => (managedField ? groupLockNote(props.row, what) : '')

const update = (patch: Partial<InterfaceDraftRow>) => emit('update', patch)
</script>

<template>
  <tr class="iface-row">
    <td class="col-select">
      <input type="checkbox" :checked="selected" aria-label="Выбрать интерфейс" @change="emit('select', ($event.target as HTMLInputElement).checked)" />
    </td>
    <td class="col-index">{{ index + 1 }}</td>
    <td class="col-order">
      <button type="button" class="icon-btn order-btn" :disabled="index === 0" title="Выше" aria-label="Переместить интерфейс выше" @click="emit('move', -1)">
        <svg class="icon"><use href="/icons.svg#i-chevu" /></svg>
      </button>
      <button
        type="button"
        class="icon-btn order-btn"
        :disabled="index === rows.length - 1"
        title="Ниже"
        aria-label="Переместить интерфейс ниже"
        @click="emit('move', 1)"
      >
        <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
      </button>
    </td>
    <td>
      <input
        type="text"
        class="cell-input"
        v-truncate-tooltip="row.name"
        :value="row.name"
        @input="emit('rename', ($event.target as HTMLInputElement).value)"
      />
    </td>
    <td>
      <select class="cell-input" :value="row.interface_type_id" @change="update({ interface_type_id: ($event.target as HTMLSelectElement).value })">
        <option value="">— не выбрано —</option>
        <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
      </select>
    </td>
    <td>
      <input
        type="text"
        class="cell-input"
        v-truncate-tooltip="row.mac_address"
        :value="row.mac_address"
        @input="update({ mac_address: ($event.target as HTMLInputElement).value })"
      />
    </td>
    <td>
      <select class="cell-input" :value="row.speed_id" @change="update({ speed_id: ($event.target as HTMLSelectElement).value })">
        <option value="">— не выбрано —</option>
        <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </td>
    <td class="col-check" :class="{ 'has-conflict': conflict?.flagsDiffer }">
      <input type="checkbox" :checked="row.is_management" @change="update({ is_management: ($event.target as HTMLInputElement).checked })" />
      <button
        v-if="conflict?.flagsDiffer"
        type="button"
        class="conflict-icon-btn"
        :title="conflictSummary(conflict, 'flags')"
        aria-label="Расхождение с подключённым портом — открыть варианты решения"
        @click="emit('open-conflict', 'flags')"
      >
        <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
      </button>
    </td>
    <td class="col-check" :class="{ 'has-conflict': conflict?.flagsDiffer }">
      <input type="checkbox" :checked="row.is_data_transfer" @change="update({ is_data_transfer: ($event.target as HTMLInputElement).checked })" />
    </td>
    <td>
      <button type="button" class="expand-toggle" @click="emit('toggle-expand')">
        <svg
          v-if="duplicatePorts.length"
          class="icon conflict-icon ports-dup-icon"
          :aria-label="duplicatePortsText(duplicatePorts)"
          :title="duplicatePortsText(duplicatePorts)"
        >
          <use href="/icons.svg#i-alert" />
        </svg>
        <svg
          v-if="conflict?.vlanModeDiffer"
          class="icon conflict-icon"
          aria-label="Расхождение режима порта с подключённым портом"
          :title="conflictSummary(conflict, 'vlan_mode')"
        >
          <use href="/icons.svg#i-alert" />
        </svg>
        <svg
          v-if="conflict?.allVlansDiffer"
          class="icon conflict-icon"
          aria-label="Расхождение «Все VLAN» с подключённым портом"
          :title="conflictSummary(conflict, 'all_vlans')"
        >
          <use href="/icons.svg#i-alert" />
        </svg>
        <svg v-if="staleText" class="icon conflict-icon stale-sub-icon" :aria-label="staleText" :title="staleText"><use href="/icons.svg#i-alert" /></svg>
        <span v-truncate-tooltip
          >{{ vlanCellSummary(row, vlanOptions) }} · {{ row.ips.length }} IP<template v-if="row.subinterfaces?.length">
            · {{ row.subinterfaces.length }} подинт.</template
          ><template v-if="row.connection"> · {{ connectionSummary(row, rows, deviceId) }}</template
          ><template v-if="group"> · Группа «{{ group.name }}»</template></span
        >
        <svg class="icon chev" :class="{ open: expanded }"><use href="/icons.svg#i-chevd" /></svg>
      </button>
    </td>
    <td class="col-actions">
      <button type="button" class="icon-btn danger" aria-label="Удалить интерфейс" @click="emit('remove')">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </td>
  </tr>
  <tr v-if="expanded" class="iface-detail-row">
    <td colspan="11">
      <div class="iface-detail">
        <label class="field field-wide">
          <span>Описание</span>
          <textarea :value="row.description" rows="2" @input="update({ description: ($event.target as HTMLTextAreaElement).value })"></textarea>
        </label>

        <InterfaceVlanBlock
          :row="row"
          :index="index"
          :vlan-options="vlanOptions"
          :all-vlans="isAllVlansSelected(row)"
          :managed="managed.vlan"
          :lock-note="lockNote(managed.vlan, 'Режим порта и VLAN')"
          :conflict="conflict"
          @set-mode="(mode) => emit('set-vlan-mode', mode)"
          @set-access-vlan="(vlanId) => emit('set-access-vlan', vlanId)"
          @toggle-all="(checked) => emit('toggle-all-vlans', checked)"
          @open-picker="emit('open-vlan-picker')"
          @open-conflict="(kind) => emit('open-conflict', kind)"
        />

        <InterfaceIpBlock
          :ips="row.ips"
          :managed="managed.ip"
          :lock-note="lockNote(managed.ip, 'IP-адрес и его назначение')"
          @update:ips="(ips: InterfaceIpDraftRow[]) => update({ ips })"
        />

        <!-- Подинтерфейсы порта (как у маршрутизаторов и межсетевых экранов: порт + подинтерфейс на
             номере VLAN с отдельным IP и параметрами). VLAN подинтерфейса — один из VLAN, выбранных на
             этом порту. Если порт в группе, которая задаёт подинтерфейсы, список только для просмотра:
             группа записывает в каждый свой порт полный набор «<порт>.<VLAN>». -->
        <InterfaceSubinterfacesEditor
          :model-value="row.subinterfaces ?? []"
          :parent-name="row.name"
          :vlan-options="subinterfaceVlanOptions"
          :vlan-catalog="vlanCatalog"
          :device-vlan-ids="allowedVlanIds"
          :protocol-port-catalog="protocolPortCatalog"
          :collapse-after="collapseAfter"
          :readonly="managed.subinterfaces"
          :readonly-note="lockNote(managed.subinterfaces, 'Список подинтерфейсов')"
          @update:model-value="(v) => update({ subinterfaces: v })"
        />

        <!-- Подключение порта к порту другого устройства: создаётся здесь же, при
             создании/редактировании устройства, и сохраняется тем же PUT, что и порты. -->
        <InterfaceConnectionEditor
          v-if="editConnections"
          :model-value="row.connection ?? null"
          :device-id="deviceId"
          :device-label="deviceLabel"
          :config="portConfigOf(row)"
          :taken-peer-ids="takenIds"
          :self-ports="selfPorts"
          :freed-peer-ids="freedPeerIds"
          :applying="applyingPeerConfig"
          :peers-version="peersVersion"
          @update:model-value="(v) => update({ connection: v })"
          @apply-peer-config="(peer, kinds) => emit('apply-peer-config', peer, kinds)"
          @apply-config-to-peer="(peer, kinds) => emit('apply-config-to-peer', peer, kinds)"
        />

        <InterfaceOpenPortsBlock
          :rows="rows"
          :index="index"
          :catalog-entries="protocolPortCatalog"
          :managed="managed.openPorts"
          :lock-note="lockNote(managed.openPorts, 'Список открытых портов')"
          :collapse-after="collapseAfter"
          :copy-target="copyTarget"
          @update:open-ports="(ports: OpenPortDraftRow[]) => update({ open_ports: ports })"
          @set-copy-target="(value) => emit('set-copy-target', value)"
          @copy="emit('apply-copy')"
        />
      </div>
    </td>
  </tr>
</template>

<style scoped src="../styles/interfaceTable.css"></style>
<style scoped src="../styles/interfaceCellInput.css"></style>
<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped>
/* Ячейки и колонки таблицы (td, .col-*) — styles/interfaceTable.css, общий с InterfaceBulkBar.vue. */
/* Столбец порядка: две кнопки-стрелки рядом, чтобы столбец оставался узким. */
.iface-table .col-order .order-btn {
  display: inline-flex;
}
.iface-table .col-order .order-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
/* Фикс п.3.3 (вторая часть): подсвечивает ячейку "Упр."/"Данные" интерфейса, чьё назначение
   разошлось с назначением на связанном (по активному подключению) порту другого устройства. */
.iface-table .col-check.has-conflict {
  background: var(--status-warn-soft);
  position: relative;
}
.iface-table .col-check .conflict-icon-btn {
  position: absolute;
  top: 2px;
  right: 2px;
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
</style>
