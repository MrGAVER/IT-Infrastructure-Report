<script setup lang="ts">
// Редактор подинтерфейсов ОДНОГО порта устройства или ОДНОЙ группы портов — логических интерфейсов на отдельном VLAN со
// своими IP-адресами, открытыми портами и ролью (как у маршрутизаторов и межсетевых экранов: Gi0/0.10 на VLAN 10 с адресом
// 10.0.10.1/24). Как и OpenPortListEditor.vue / VmIpListEditor.vue, компонент ничего не знает про API и сервер: получает
// список строк, отдаёт новый список через `update:modelValue`; сохранение выполняет форма устройства вместе с портами одним
// запросом (api/deviceInterfaces.ts:persistDeviceInterfaces), а проверка при сохранении — общая с формой функция
// utils/subinterfaces.ts:validateSubinterfaceRows. Здесь только подсказки по ходу ввода.
//
// Вид — таблица, как «Список интерфейсов»: «Имя», «VLAN», «Управление», «Данные» и разворачиваемый столбец «IP-адреса / маски».
// Столбец по умолчанию свёрнут и показывает адреса с масками (10.0.10.1/24); раскрытая строка — формы IP-адресов и открытых
// портов подинтерфейса (и описание).
//
// Правила, которые редактор помогает соблюсти (серверные зеркальны — backend/app/services/crud/subinterfaces.py):
//  • VLAN подинтерфейса выбирается ТОЛЬКО из VLAN, выбранных на этом порту (vlanOptions; у группы — из VLAN группы) и
//    только из ещё не занятых другими подинтерфейсами порта: на порту VLAN используется один раз, уже выбранные в списке
//    не показываются (собственный выбор строки остаётся). Список — SearchableSelect: ищется по номеру, имени и домену VLAN.
//    Он в режиме floating: таблица лежит в контейнере с overflow-x: auto, который обрезал бы выпадающий список по высоте
//    (список уходил под край блока, и блок приходилось прокручивать) — панель выводится поверх, в <body>;
//  • имя подинтерфейса уникально на устройстве (это проверяет форма при сохранении).
//
// mode='group': подинтерфейс группы — шаблон, который записывается в каждый порт группы с именем `<порт>.<номер VLAN>`, поэтому
// своего имени у шаблона нет (в столбце «Имя» — образец). readonly — подинтерфейсы заданы группой портов, здесь только просмотр.
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { useSubinterfaceRows } from '../composables/useSubinterfaceRows'
import ScrollableTableWrap from './ScrollableTableWrap.vue'
import type { ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import SubinterfaceDetail from './SubinterfaceDetail.vue'
import SubinterfaceVlanWarning from './SubinterfaceVlanWarning.vue'
import SearchableSelect from './SearchableSelect.vue'

const props = withDefaults(
  defineProps<{
    modelValue: SubinterfaceDraftRow[]
    /** Имя порта-родителя: из него строится подсказка имени «<порт>.<VLAN>». У группы не используется. */
    parentName: string
    /** VLAN, из которых можно выбрать: VLAN, выбранные на порту (у группы — VLAN группы). */
    vlanOptions: VLANDefinition[]
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    /** Порог сворачивания списка открытых портов подинтерфейса (общий порог из «Настроек»); не передан — без сворачивания. */
    collapseAfter?: number
    /** Все известные VLAN (справочник), включая уже недоступные порту: по ним для подинтерфейса на снятом VLAN
     * известен номер (подпись в предупреждении, пересчёт автоимени при переносе). Без него — только vlanOptions. */
    vlanCatalog?: VLANDefinition[]
    /** Id VLAN, назначенных устройству: отличает «VLAN снят с устройства» от «VLAN не выбран на порту» в предупреждении. */
    deviceVlanIds?: ReadonlySet<string>
    mode?: 'port' | 'group'
    /** Подинтерфейсы заданы группой портов: редактирование выключено. */
    readonly?: boolean
    /** Пояснение над таблицей (например, «Подинтерфейсы заданы группой «X»…»). */
    readonlyNote?: string
  }>(),
  { protocolPortCatalog: () => [], vlanCatalog: () => [], mode: 'port', readonly: false, readonlyNote: '' },
)
const emit = defineEmits<{ 'update:modelValue': [rows: SubinterfaceDraftRow[]] }>()

// Состояние и правила (свободные VLAN, автоимя, предупреждение о недоступном VLAN, раскрытие строк) — composables/useSubinterfaceRows.ts.
const {
  isGroup,
  ownerWord,
  hint,
  expanded,
  toggleExpand,
  updateRow,
  freeVlans,
  hasFreeVlan,
  isStaleVlan,
  staleVlanLabel,
  staleReason,
  vlanChoices,
  groupNamePattern,
  addRow,
  removeRow,
  onVlanChange,
  ipSummary,
  emptyText,
  addTitle,
} = useSubinterfaceRows(props, emit)
</script>

<template>
  <div class="sub-block">
    <div class="sub-head">
      <div class="sub-title">
        <b>Подинтерфейсы</b>
        <span class="hint">
          {{ hint }}
        </span>
      </div>
      <button v-if="!readonly" type="button" class="btn btn-secondary" :disabled="!vlanOptions.length || !hasFreeVlan" :title="addTitle" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Подинтерфейс
      </button>
    </div>

    <div v-if="readonlyNote" class="group-lock">{{ readonlyNote }}</div>

    <div v-if="!modelValue.length" class="empty">{{ emptyText }}</div>

    <ScrollableTableWrap v-else label="Подинтерфейсы">
      <table class="sub-table">
        <thead>
          <tr>
            <th>Имя</th>
            <th class="col-vlan">VLAN</th>
            <th class="col-check">Управление</th>
            <th class="col-check">Данные</th>
            <th>IP-адреса / маски</th>
            <th v-if="!readonly" class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(sub, i) in modelValue" :key="sub.key">
            <tr class="sub-row">
              <td>
                <span v-if="isGroup" class="name-pattern">{{ groupNamePattern(sub) }}</span>
                <input
                  v-else
                  type="text"
                  class="cell-input"
                  :value="sub.name"
                  :disabled="readonly"
                  placeholder="Например, Gi0/0.10"
                  maxlength="100"
                  aria-label="Имя подинтерфейса"
                  @input="updateRow(i, { name: ($event.target as HTMLInputElement).value })"
                />
              </td>
              <td class="col-vlan">
                <SearchableSelect
                  class="vlan-select"
                  :class="{ 'is-stale': isStaleVlan(sub) }"
                  aria-label="VLAN подинтерфейса"
                  :model-value="sub.vlan_id"
                  :options="vlanChoices(i)"
                  :disabled="readonly"
                  floating
                  placeholder="— выберите VLAN —"
                  :empty-text="`Все VLAN ${ownerWord} уже использованы`"
                  @update:model-value="(v) => onVlanChange(i, v)"
                />
              </td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="sub.is_management"
                  :disabled="readonly"
                  aria-label="Подинтерфейс: управление"
                  @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })"
                />
              </td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="sub.is_data_transfer"
                  :disabled="readonly"
                  aria-label="Подинтерфейс: передача данных"
                  @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })"
                />
              </td>
              <td>
                <button
                  type="button"
                  class="expand-toggle"
                  :aria-expanded="expanded.has(sub.key)"
                  aria-label="Показать IP-адреса и открытые порты подинтерфейса"
                  @click="toggleExpand(sub.key)"
                >
                  <span v-if="ipSummary(sub)" v-truncate-tooltip class="ip-summary">{{ ipSummary(sub) }}</span>
                  <span v-else class="ip-none">нет IP</span>
                  <span v-if="sub.open_ports.length" class="ports-count">· портов: {{ sub.open_ports.length }}</span>
                  <svg class="icon chev" :class="{ open: expanded.has(sub.key) }"><use href="/icons.svg#i-chevd" /></svg>
                </button>
              </td>
              <td v-if="!readonly" class="col-actions">
                <button type="button" class="icon-btn danger" aria-label="Удалить подинтерфейс" @click="removeRow(i)">
                  <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                </button>
              </td>
            </tr>

            <tr v-if="isStaleVlan(sub)" class="sub-warn-row">
              <td :colspan="readonly ? 5 : 6">
                <SubinterfaceVlanWarning
                  :reason="staleReason(sub)"
                  :vlan-label-text="staleVlanLabel(sub)"
                  :is-group="isGroup"
                  :owner-word="ownerWord"
                  :readonly="readonly"
                  :free-vlans="freeVlans(i)"
                  @move="(vlanId) => onVlanChange(i, vlanId)"
                />
              </td>
            </tr>

            <tr v-if="expanded.has(sub.key)" class="sub-detail-row">
              <td :colspan="readonly ? 5 : 6">
                <SubinterfaceDetail
                  :sub="sub"
                  :readonly="readonly"
                  :protocol-port-catalog="protocolPortCatalog"
                  :collapse-after="collapseAfter"
                  @update="(patch) => updateRow(i, patch)"
                />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </ScrollableTableWrap>
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
.group-lock {
  font-size: 11px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 2px 0;
}
/* Таблица подинтерфейсов — тот же вид, что у «Списка интерфейсов» (DeviceInterfacesEditor.vue). */
.sub-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.sub-table th {
  text-align: left;
  font-weight: 600;
  color: var(--ink-muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  padding: 0 6px 6px;
  white-space: nowrap;
}
.sub-table td {
  padding: 4px 6px;
  vertical-align: middle;
  border-top: 1px solid var(--border);
}
.sub-table .col-vlan {
  min-width: 190px;
}
.sub-table .col-check,
.sub-table .col-actions {
  width: 1%;
  white-space: nowrap;
  text-align: center;
}
.sub-table .col-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
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
  min-width: 110px;
  box-sizing: border-box;
}
.name-pattern {
  color: var(--ink-muted);
  font-size: 12px;
  white-space: nowrap;
}
.vlan-select.is-stale :deep(input) {
  border-color: var(--status-crit);
}
.expand-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 4px 2px;
  font-size: 11.5px;
  color: var(--ink);
  cursor: pointer;
  white-space: nowrap;
  max-width: 100%;
}
.expand-toggle:hover .chev {
  color: var(--ink);
}
.ip-none,
.ports-count {
  color: var(--ink-muted);
}
.ip-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform 0.15s;
  flex-shrink: 0;
  color: var(--ink-muted);
}
.chev.open {
  transform: rotate(180deg);
}
.sub-warn-row td,
.sub-detail-row td {
  border-top: none;
  padding-top: 0;
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
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
