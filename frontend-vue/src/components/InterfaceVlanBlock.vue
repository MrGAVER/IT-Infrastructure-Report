<script setup lang="ts">
// Блок «Режим порта и VLAN» раскрытой строки порта: Trunk / Access, в access — один VLAN из списка с поиском, в trunk — галочка
// «Все VLAN» и кнопка окна выбора VLAN (PortVlanPickerModal.vue: при многих VLAN список растягивал бы карточку порта).
// Блок только показывает значения и сообщает о действиях: что записать в порт, решают useVlanSelection и useNeighborSync родителя.
import { computed } from 'vue'
import type { InterfaceDraftRow, PortConflictInfo, VLANDefinition, VlanMode } from '../api/types'
import type { ConflictKind } from '../utils/interfaceRowView'
import { conflictSummary, trunkVlanSummary, trunkVlanTitle } from '../utils/interfaceRowView'
import { vlanLabel } from '../utils/vlan'
import SearchableSelect from './SearchableSelect.vue'

const props = defineProps<{
  row: InterfaceDraftRow
  /** Номер строки — делает уникальным name радиокнопок режима порта. */
  index: number
  /** VLAN, доступные порту (список приходит готовым от вызывающей стороны, см. api/portVlans.ts: computePortVlanOptions). */
  vlanOptions: VLANDefinition[]
  /** Признак «Все VLAN» порта (utils/allVlans.ts: isAllVlansSelected). */
  allVlans: boolean
  /** Режим порта и VLAN задаёт группа портов: поля только для просмотра. */
  managed: boolean
  /** Подсказка о группе, показывается у заблокированных полей. */
  lockNote: string
  /** Расхождение с портом на другом конце подключения (значки-предупреждения и вход в окно решения). */
  conflict: PortConflictInfo | undefined
}>()
const emit = defineEmits<{
  'set-mode': [mode: VlanMode]
  'set-access-vlan': [vlanId: string]
  'toggle-all': [checked: boolean]
  'open-picker': []
  'open-conflict': [kind: ConflictKind]
}>()

// Access-порт: VLAN выбирается из списка с поиском (SearchableSelect) — VLAN у устройства может быть много.
const accessVlanOptions = computed(() => props.vlanOptions.map((v) => ({ value: v.id, label: vlanLabel(v) })))
</script>

<template>
  <div class="vlan-block">
    <div class="vlan-mode-row">
      <b>Режим порта</b>
      <span v-if="managed" class="group-lock">{{ lockNote }}</span>
      <button
        v-if="conflict?.vlanModeDiffer"
        type="button"
        class="conflict-icon-btn"
        :title="conflictSummary(conflict, 'vlan_mode')"
        aria-label="Расхождение режима порта с подключённым портом — открыть варианты решения"
        @click="emit('open-conflict', 'vlan_mode')"
      >
        <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
      </button>
      <label class="radio-inline">
        <input type="radio" :name="`vlan-mode-${index}`" :checked="row.vlan_mode !== 'access'" :disabled="managed" @change="emit('set-mode', 'trunk')" />
        Trunk
      </label>
      <label class="radio-inline">
        <input type="radio" :name="`vlan-mode-${index}`" :checked="row.vlan_mode === 'access'" :disabled="managed" @change="emit('set-mode', 'access')" />
        Access
      </label>
    </div>

    <template v-if="row.vlan_mode === 'access'">
      <div v-if="vlanOptions.length" class="field">
        <span>VLAN порта (access — ровно один)</span>
        <SearchableSelect
          :model-value="row.vlan_ids[0] ?? ''"
          :options="accessVlanOptions"
          :disabled="managed"
          placeholder="— не выбрано —"
          @update:model-value="(v) => emit('set-access-vlan', v)"
        />
      </div>
      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
    </template>
    <template v-else>
      <!-- Список VLAN trunk-порта вынесен во всплывающее окно (PortVlanPickerModal): при многих VLAN он растягивал
           карточку порта. Галочка «Все VLAN» остаётся рядом с кнопкой, открывающей окно. -->
      <div v-if="vlanOptions.length" class="trunk-row">
        <label class="vlan-check vlan-check-all">
          <input type="checkbox" :checked="allVlans" :disabled="managed" @change="emit('toggle-all', ($event.target as HTMLInputElement).checked)" />
          <b>Все VLAN</b>
        </label>
        <button
          v-if="conflict?.allVlansDiffer"
          type="button"
          class="conflict-icon-btn"
          data-testid="all-vlans-conflict"
          :title="conflictSummary(conflict, 'all_vlans')"
          aria-label="Расхождение «Все VLAN» с подключённым портом — открыть варианты решения"
          @click="emit('open-conflict', 'all_vlans')"
        >
          <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
        </button>
        <span class="vlan-summary" :title="trunkVlanTitle(row, vlanOptions)">{{ trunkVlanSummary(row, vlanOptions) }}</span>
        <button type="button" class="btn btn-secondary vlan-picker-btn" @click="emit('open-picker')">
          {{ managed ? 'Показать VLAN…' : 'Выбрать VLAN…' }}
        </button>
      </div>
      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
    </template>
  </div>
</template>

<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped src="../styles/interfaceVlanControls.css"></style>
<style scoped>
.vlan-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vlan-block b {
  font-size: 11.5px;
}
.vlan-mode-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.radio-inline {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.radio-inline input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
  margin: 0;
}
.trunk-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
}
.trunk-row .vlan-check-all {
  margin-right: 0;
}
.vlan-summary {
  font-size: 12px;
  color: var(--ink-muted);
}
</style>
