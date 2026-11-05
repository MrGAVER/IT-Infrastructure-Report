<script setup lang="ts">
// Окно выбора VLAN trunk-порта (блок «Порты / интерфейсы» формы устройства). Список VLAN устройства может быть
// длинным, и инлайновые чекбоксы растягивали карточку порта, поэтому выбор вынесен во всплывающее окно — как у групп
// портов (InterfaceGroupsPanel.vue) и массового редактирования: поиск по номеру, имени и домену, счётчик выбранных и
// галочка «Все VLAN». Сама галочка остаётся и в строке порта — рядом с кнопкой, открывающей это окно.
//
// Компонент ничего не хранит: набор выбранных VLAN и признак «Все VLAN» приходят от родителя, каждое изменение уходит
// событием (родитель применяет те же правила, что и раньше: ручной выбор снимает признак, «Все VLAN» отмечает весь список).
// «Все VLAN» действует на ВСЕ VLAN устройства, а не только на найденные поиском.
//
// @example
// <PortVlanPickerModal
//   title="VLAN порта «Gi0/1»" :options="vlanOptions" :selected-ids="row.vlan_ids" :all-vlans="row.all_vlans === true"
//   @toggle-vlan="(id, checked) => toggleVlan(i, id, checked)" @toggle-all="(checked) => toggleAllVlans(i, checked)" @close="picker = null"
// />
import { computed, ref } from 'vue'
import type { VLANDefinition } from '../api/types'
import BaseModal from './BaseModal.vue'
import { filterVlansByQuery, vlanLabel } from '../utils/vlan'

const props = withDefaults(
  defineProps<{
    title: string
    /** VLAN, допустимые устройству порта. */
    options: VLANDefinition[]
    /** Id выбранных VLAN (у порта с «Все VLAN» — все VLAN устройства: форма так показывает их отмеченными). */
    selectedIds: readonly string[]
    allVlans: boolean
    /** Только просмотр: набор задаёт группа портов (или правка недоступна) — галочки недоступны, причина — в readonlyNote. */
    readonly?: boolean
    readonlyNote?: string
  }>(),
  { readonly: false, readonlyNote: '' },
)
const emit = defineEmits<{
  close: []
  'toggle-vlan': [vlanId: string, checked: boolean]
  'toggle-all': [checked: boolean]
}>()

const search = ref('')
const filtered = computed(() => filterVlansByQuery(props.options, search.value))
const selected = computed(() => new Set(props.selectedIds))
const selectedCount = computed(() => props.options.filter((v) => selected.value.has(v.id)).length)
</script>

<template>
  <BaseModal :offset="60" data-testid="port-vlan-picker" @close="emit('close')">
    <div class="vlan-picker-modal card" role="dialog" aria-modal="true" :aria-label="title">
      <div class="picker-head">
        <h3>{{ title }}</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p v-if="readonlyNote" class="picker-note">{{ readonlyNote }}</p>
      <div class="picker-search">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="search" type="text" placeholder="Поиск по номеру, имени, домену…" aria-label="Поиск VLAN" />
      </div>
      <div class="picker-summary">Выбрано VLAN: {{ selectedCount }} из {{ options.length }}</div>
      <p v-if="allVlans && !readonly" class="picker-note">
        Включён признак «Все VLAN»: порт несёт и VLAN, добавленные устройству позже. Снятие любого VLAN уберёт признак.
      </p>
      <div class="vlan-checks vlan-picker-list">
        <label class="vlan-check vlan-check-all">
          <input type="checkbox" :checked="allVlans" :disabled="readonly" @change="emit('toggle-all', ($event.target as HTMLInputElement).checked)" />
          <b>Все VLAN</b>
        </label>
        <label v-for="v in filtered" :key="v.id" class="vlan-check">
          <input
            type="checkbox"
            :checked="selected.has(v.id)"
            :disabled="readonly"
            @change="emit('toggle-vlan', v.id, ($event.target as HTMLInputElement).checked)"
          />
          {{ vlanLabel(v) }}
        </label>
        <span v-if="!filtered.length" class="picker-empty">Ничего не найдено</span>
      </div>
      <div class="picker-foot">
        <button type="button" class="btn btn-primary" @click="emit('close')">Готово</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.vlan-picker-modal {
  width: 100%;
  max-width: 360px;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}
.picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.picker-head h3 {
  font-family: var(--font-display);
  font-size: 14.5px;
  margin: 0;
}
.picker-search {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 7px 10px;
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
  font-size: 12px;
  color: var(--ink-muted);
  margin: 8px 0;
}
.picker-note {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0 0 8px;
}
.vlan-checks {
  display: flex;
  flex-direction: column;
  flex-wrap: nowrap;
  gap: 6px;
}
.vlan-picker-list {
  overflow-y: auto;
  margin-bottom: 14px;
}
.vlan-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
}
.vlan-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.vlan-check-all {
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.picker-empty {
  font-size: 12.5px;
  color: var(--ink-muted);
}
.picker-foot {
  display: flex;
  justify-content: flex-end;
}
</style>
