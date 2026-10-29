<script setup lang="ts">
// Блок «Скопировать значения с порта» окна группы портов (GroupEditModal.vue): выбор порта устройства и параметров, которые
// заполнят черновик группы значениями этого порта. Черновик не мутируется — новый отдаётся событием apply
// (логика и уведомления — composables/useGroupCopy.ts).
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useGroupCopy } from '../composables/useGroupCopy'
import SearchableSelect from './SearchableSelect.vue'

const props = defineProps<{
  rows: InterfaceDraftRow[]
  draft: InterfaceGroupDraft
  vlanOptions: VLANDefinition[]
  protocolPortCatalog: ProtocolPortCatalogEntry[]
}>()
const emit = defineEmits<{ apply: [group: InterfaceGroupDraft] }>()

const { copySource, copyWhat, copyPortOptions, copyRow, copyAvailable, copyNothingAvailable, canCopy, copyFromPort } = useGroupCopy({
  rows: () => props.rows,
  vlanOptions: () => props.vlanOptions,
  protocolPortCatalog: () => props.protocolPortCatalog,
  draft: () => props.draft,
  apply: (group) => emit('apply', group),
})
</script>

<template>
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
      <label class="check-inline" :class="{ disabled: !copyAvailable.subinterfaces }">
        <input v-model="copyWhat.subinterfaces" type="checkbox" :disabled="!copyAvailable.subinterfaces" aria-label="Скопировать подинтерфейсы" /> Подинтерфейсы
      </label>
      <span v-if="copyNothingAvailable" class="hint">У порта нет значений, которые можно скопировать.</span>
    </div>
  </div>
</template>

<style scoped src="../styles/groupPanelShared.css"></style>
<style scoped>
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
</style>
