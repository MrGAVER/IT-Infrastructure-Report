<script setup lang="ts">
// Окно создания/правки группы портов (InterfaceGroupsPanel.vue): наименование, состав группы и общие параметры — режим порта
// и VLAN, общий IP-адрес (с префиксом и назначением), открытые порты и подинтерфейсы (правка формы устройства, п.4).
//
// Окно работает с собственной копией группы и ничего не применяет: «Создать группу»/«Применить» отдаёт родителю событие
// save с черновиком и составом, закрытие — событие close. Окно создаётся заново при каждом открытии, поэтому состояние
// (копирование с порта, окно выбора VLAN) не переживает закрытие.
import { computed, ref } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { cloneGroupForEdit, countSelectedVlans, groupSubinterfaceVlans, setGroupAccessVlan, setGroupAllVlans, setGroupVlanMode, toggleGroupVlan } from '../utils/groupDraftEdit'
import { vlanLabel } from '../utils/vlan'
import GroupCopyBlock from './GroupCopyBlock.vue'
import GroupVlanPickerModal from './GroupVlanPickerModal.vue'
import InterfaceSubinterfacesEditor from './InterfaceSubinterfacesEditor.vue'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SearchableSelect from './SearchableSelect.vue'

const props = defineProps<{
  /** Исходная группа (новая — пустая): окно правит копию. */
  group: InterfaceGroupDraft
  isNew: boolean
  /** Индексы портов, входящих в группу при открытии окна. */
  members: ReadonlySet<number>
  rows: InterfaceDraftRow[]
  groups: InterfaceGroupDraft[]
  vlanOptions: VLANDefinition[]
  protocolPortCatalog: ProtocolPortCatalogEntry[]
  // Порог сворачивания списка открытых портов группы (общий порог из «Настроек»); не передан — без сворачивания.
  collapseAfter?: number
}>()
const emit = defineEmits<{ close: []; save: [payload: { group: InterfaceGroupDraft; members: Set<number> }] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

// draft — рабочая копия группы; members — индексы её портов (чисто UI-состояние окна до «Сохранить»).
const draft = ref<InterfaceGroupDraft>(cloneGroupForEdit(props.group))
const members = ref<Set<number>>(new Set(props.members))

function toggleMember(index: number, checked: boolean) {
  const next = new Set(members.value)
  if (checked) next.add(index)
  else next.delete(index)
  members.value = next
}

/** Порт другой группы можно забрать в эту (он перейдёт в неё), но об этом стоит предупредить. */
function otherGroupName(index: number): string | null {
  const key = props.rows[index]?.group_key
  if (!key || key === draft.value.key) return null
  return props.groups.find((g) => g.key === key)?.name ?? null
}

// --- Режим порта и VLAN -----------------------------------------------------------------------
function setMode(mode: InterfaceGroupDraft['vlan_mode']) {
  draft.value = setGroupVlanMode(draft.value, mode, props.vlanOptions)
}

function toggleVlan(vlanId: string, checked: boolean) {
  draft.value = toggleGroupVlan(draft.value, vlanId, checked)
}

/** «Все VLAN» в Trunk-режиме — как у порта (DeviceInterfacesEditor.vue): сохраняемый признак группы, а не вывод из числа
 * выбранных VLAN. */
const isAllVlansSelected = computed(() => draft.value.all_vlans === true)

function toggleAllVlans(checked: boolean) {
  draft.value = setGroupAllVlans(draft.value, checked, props.vlanOptions)
}

// Выбор отдельных VLAN — во всплывающем окне (как в массовом редактировании портов); в самом окне группы остаются
// «Все VLAN», сводка и кнопка.
const vlanPickerOpen = ref(false)
const selectedVlanCount = computed(() => countSelectedVlans(draft.value.vlan_ids, props.vlanOptions))
const vlanSelectOptions = computed(() => props.vlanOptions.map((v) => ({ value: v.id, label: vlanLabel(v) })))

// VLAN, из которых выбирается VLAN подинтерфейса группы.
const groupVlanOptions = computed(() => groupSubinterfaceVlans(draft.value, props.vlanOptions))

function setDraftSubinterfaces(rows: SubinterfaceDraftRow[]) {
  draft.value = { ...draft.value, subinterfaces: rows }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="group-modal card" role="dialog" aria-modal="true" :aria-label="isNew ? 'Новая группа портов' : 'Группа портов'">
      <div class="modal-head">
        <h2>{{ isNew ? 'Новая группа портов' : 'Группа портов' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
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

          <GroupCopyBlock :rows="rows" :draft="draft" :vlan-options="vlanOptions" :protocol-port-catalog="protocolPortCatalog" @apply="(g) => (draft = g)" />

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
              @update:model-value="(v) => (draft = setGroupAccessVlan(draft, v))"
            />
            <div v-else-if="draft.vlan_mode === 'trunk'" class="trunk-row">
              <span v-if="!vlanOptions.length" class="empty">Для типа устройства VLAN не назначены</span>
              <template v-else>
                <label class="check-inline vlan-check-all">
                  <input type="checkbox" :checked="isAllVlansSelected" @change="toggleAllVlans(($event.target as HTMLInputElement).checked)" />
                  <b>Все VLAN</b>
                </label>
                <span class="vlan-summary">Выбрано VLAN: {{ selectedVlanCount }} из {{ vlanOptions.length }}</span>
                <button type="button" class="btn btn-secondary vlan-picker-btn" @click="vlanPickerOpen = true">Выбрать VLAN…</button>
              </template>
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
                @input="draft = { ...draft, prefix_length: ($event.target as HTMLInputElement).value }"
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
            <OpenPortListEditor
              v-if="draft.manage_open_ports"
              v-model="draft.open_ports"
              :catalog-entries="protocolPortCatalog"
              :collapse-after="collapseAfter"
              sorted-unique
            />
          </div>

          <div class="param subs-param">
            <label class="param-head manage-check">
              <input v-model="draft.manage_subinterfaces" type="checkbox" aria-label="Задать подинтерфейсы" />
              <b>Задать подинтерфейсы</b>
              <span class="hint">заменит подинтерфейсы этих портов; у каждого порта — «‹порт›.‹VLAN›»</span>
            </label>
            <InterfaceSubinterfacesEditor
              v-if="draft.manage_subinterfaces"
              mode="group"
              parent-name=""
              :model-value="draft.subinterfaces ?? []"
              :vlan-options="groupVlanOptions"
              :vlan-catalog="vlanOptions"
              :protocol-port-catalog="protocolPortCatalog"
              :collapse-after="collapseAfter"
              @update:model-value="setDraftSubinterfaces"
            />
          </div>
        </section>
      </div>

      <div class="modal-foot group-modal-actions">
        <button type="button" class="btn btn-secondary" @click="emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" @click="emit('save', { group: draft, members })">{{ isNew ? 'Создать группу' : 'Применить' }}</button>
      </div>
    </div>
  </div>

  <GroupVlanPickerModal
    v-if="vlanPickerOpen"
    :vlan-options="vlanOptions"
    :vlan-ids="draft.vlan_ids"
    :all-vlans="isAllVlansSelected"
    @toggle="toggleVlan"
    @toggle-all="toggleAllVlans"
    @close="vlanPickerOpen = false"
  />
</template>

<style scoped src="../styles/groupModal.css"></style>
<style scoped src="../styles/groupPanelShared.css"></style>
<style scoped>
/* Внешний вид приведён к остальным окнам приложения (QuickAddModal, DeviceInterfacesEditor):
   в приложении нет глобальных стилей для полей ввода — каждый компонент красит их сам, поэтому
   необъявленные здесь input/радио/чекбоксы оставались нативными (светлыми). */
.group-modal {
  width: 100%;
  padding: 20px 22px 18px;
  max-width: 680px;
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
.manage-check {
  align-items: center;
  cursor: pointer;
}

.mode-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}
.trunk-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.vlan-picker-btn {
  white-space: nowrap;
}

.ip-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px minmax(0, 1fr);
  gap: 8px;
}

@media (max-width: 520px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
