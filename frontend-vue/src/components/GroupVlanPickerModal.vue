<script setup lang="ts">
// Окно выбора VLAN группы портов (GroupEditModal.vue): отдельные VLAN выбираются здесь (как в массовом редактировании
// портов) — при большом числе VLAN инлайновый список растягивал окно группы. «Все VLAN» действует на ВСЕ VLAN устройства,
// а не только на найденные поиском. Состояние выбора принадлежит окну группы: окно только показывает его и сообщает о кликах.
import { computed, ref } from 'vue'
import type { VLANDefinition } from '../api/types'
import BaseModal from './BaseModal.vue'
import { countSelectedVlans } from '../utils/groupDraftEdit'
import { filterVlansByQuery, vlanLabel } from '../utils/vlan'

const props = defineProps<{
  vlanOptions: VLANDefinition[]
  /** id выбранных VLAN. */
  vlanIds: string[]
  allVlans: boolean
}>()
const emit = defineEmits<{ close: []; toggle: [vlanId: string, checked: boolean]; 'toggle-all': [checked: boolean] }>()

// Поиск не переживает закрытие окна: окно создаётся заново при каждом открытии, при повторном открытии список полный.
const search = ref('')
const filteredVlanOptions = computed(() => filterVlansByQuery(props.vlanOptions, search.value))
const selectedCount = computed(() => countSelectedVlans(props.vlanIds, props.vlanOptions))
</script>

<template>
  <BaseModal @close="emit('close')">
    <div class="vlan-picker-modal card" role="dialog" aria-modal="true" aria-label="Выбор VLAN группы">
      <div class="modal-head">
        <h2>Выбор VLAN группы</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <div class="picker-search">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="search" type="text" placeholder="Поиск по номеру, имени, домену…" aria-label="Поиск VLAN" />
      </div>
      <div class="vlan-summary picker-summary">Выбрано VLAN: {{ selectedCount }} из {{ vlanOptions.length }}</div>
      <div class="vlan-checks vlan-picker-list">
        <!-- «Все VLAN» действует на ВСЕ VLAN устройства, а не только на найденные поиском -->
        <label class="check-inline vlan-check-all">
          <input type="checkbox" :checked="allVlans" @change="emit('toggle-all', ($event.target as HTMLInputElement).checked)" />
          <b>Все VLAN</b>
        </label>
        <label v-for="v in filteredVlanOptions" :key="v.id" class="check-inline">
          <input type="checkbox" :checked="vlanIds.includes(v.id)" @change="emit('toggle', v.id, ($event.target as HTMLInputElement).checked)" />
          {{ vlanLabel(v) }}
        </label>
        <span v-if="!filteredVlanOptions.length" class="picker-empty">Ничего не найдено</span>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn btn-primary" @click="emit('close')">Готово</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped src="../styles/groupModal.css"></style>
<style scoped src="../styles/groupPanelShared.css"></style>
<style scoped>
.vlan-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  max-height: 180px;
  overflow-y: auto;
}
/* окно выбора VLAN — поверх окна группы (тот же z-index, но позже в DOM) */
.vlan-picker-modal {
  width: 100%;
  max-width: 360px;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}
.vlan-picker-modal .vlan-picker-list {
  flex-direction: column;
  flex-wrap: nowrap;
  max-height: none;
  overflow-y: auto;
}
.vlan-picker-modal .modal-foot {
  margin-top: 14px;
}
.picker-search {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 7px 10px;
  margin-top: 4px;
}
.picker-search .icon {
  color: var(--ink-muted);
}
.picker-search input {
  border: none;
  background: transparent;
  outline: none;
  color: var(--ink);
  font-size: 12.5px;
  width: 100%;
}
.picker-summary {
  margin: 8px 0;
}
.picker-empty {
  font-size: 12.5px;
  color: var(--ink-muted);
}
</style>
