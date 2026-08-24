<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useVLANsStore } from '../stores/vlans'
import { useCatalogsStore } from '../stores/catalogs'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { VLANDefinition } from '../api/types'
import StatCard from '../components/StatCard.vue'
import VLANFormModal from '../components/VLANFormModal.vue'

const vlans = useVLANsStore()
const catalogs = useCatalogsStore()
const { notify, notifyError } = useToast()

const modalDefinition = ref<VLANDefinition | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([vlans.ensureLoaded(), catalogs.ensureLoaded()])
})

function openCreate() {
  modalDefinition.value = null
  modalOpen.value = true
}
function openEdit(d: VLANDefinition) {
  modalDefinition.value = d
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalDefinition.value = null
}
async function onSaved() {
  const wasEdit = modalDefinition.value !== null
  closeModal()
  await vlans.reload()
  notify(wasEdit ? 'VLAN обновлён' : 'VLAN добавлен', 'success')
}

async function removeDefinition(d: VLANDefinition) {
  if (!confirm(`Удалить определение VLAN ${d.vlan_id} «${d.name}»?`)) return
  deletingId.value = d.id
  try {
    await deleteResource('vlans', d.id)
    await vlans.reload()
    notify('VLAN удалён', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="vlans-view">
    <div class="stat-row">
      <StatCard :value="vlans.groups.length" label="Уникальных VLAN ID" />
      <StatCard :value="vlans.definitionCount" label="Определений всего" />
      <StatCard :value="vlans.conflictingVlanIds.length" label="ID с разными именами по доменам" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="vlans.search" type="text" placeholder="Поиск по VLAN ID, имени, домену, устройству…" />
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="vlans.loading" @click="vlans.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить VLAN
      </button>
    </div>

    <div v-if="vlans.error" class="error-banner card">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
      {{ vlans.error }}
    </div>
    <div v-else-if="vlans.loading && !vlans.loaded" class="loading-banner">Загрузка VLAN…</div>
    <div v-else-if="!vlans.filtered.length" class="empty-banner card">Ничего не найдено по заданным фильтрам.</div>

    <div v-else class="groups">
      <div v-for="g in vlans.filtered" :key="g.vlan_id" class="group card" :class="{ conflict: vlans.conflictingVlanIds.includes(g.vlan_id) }">
        <div class="group-head">
          <span class="vlan-id mono">VLAN {{ g.vlan_id }}</span>
          <span v-if="vlans.conflictingVlanIds.includes(g.vlan_id)" class="conflict-badge">разные имена по доменам</span>
        </div>

        <div v-for="d in g.definitions" :key="d.id" class="definition">
          <div class="definition-main">
            <div>
              <span class="def-name">{{ d.name }}</span>
              <span class="def-domain">{{ d.domain_name }}</span>
              <span v-if="d.description" class="def-desc">{{ d.description }}</span>
            </div>
            <div class="row-actions">
              <button type="button" aria-label="Редактировать" @click="openEdit(d)">
                <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
              </button>
              <button type="button" aria-label="Удалить" :disabled="deletingId === d.id" @click="removeDefinition(d)">
                <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
              </button>
            </div>
          </div>
          <div v-if="d.devices.length" class="device-chips">
            <span v-for="dev in d.devices" :key="dev.device_id" class="device-chip" :class="{ mgmt: dev.is_management }">
              {{ dev.device_name }}
              <span v-if="dev.ip_address" class="mono">· {{ dev.ip_address }}</span>
              <span v-if="dev.is_management" class="mgmt-tag">упр.</span>
            </span>
          </div>
          <p v-else class="no-devices">Нет привязанных устройств.</p>
        </div>
      </div>
    </div>

    <VLANFormModal v-if="modalOpen" :definition="modalDefinition" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 7px 10px;
  min-width: 260px;
  max-width: 420px;
}
.search-box .icon {
  color: var(--ink-muted);
}
.search-box input {
  border: none;
  background: transparent;
  outline: none;
  color: var(--ink);
  font-size: 12.5px;
  width: 100%;
}
.spacer {
  flex: 1;
}
.error-banner,
.empty-banner {
  padding: 20px;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.error-banner {
  color: var(--status-crit);
  display: flex;
  align-items: center;
  gap: 8px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group {
  padding: 14px 16px;
}
.group.conflict {
  border-color: var(--status-warn);
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.vlan-id {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 14px;
  color: var(--brand);
}
.conflict-badge {
  font-size: 10.5px;
  color: var(--status-warn);
  background: var(--status-warn-soft, rgba(232, 163, 61, 0.15));
  padding: 2px 8px;
  border-radius: 20px;
  font-weight: 600;
}
.definition {
  padding: 10px 0;
  border-top: 1px solid var(--border);
}
.definition:first-of-type {
  border-top: none;
}
.definition-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.def-name {
  font-weight: 600;
  font-size: 13px;
}
.def-domain {
  display: block;
  font-size: 11px;
  color: var(--ink-muted);
  margin-top: 1px;
}
.def-desc {
  display: block;
  font-size: 11.5px;
  color: var(--ink-muted);
  margin-top: 3px;
}
.device-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.device-chip {
  font-size: 11px;
  color: var(--ink);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 9px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.device-chip.mgmt {
  border-color: var(--brand);
}
.mgmt-tag {
  font-size: 9.5px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
}
.no-devices {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 6px 0 0;
  font-style: italic;
}
.row-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.row-actions button {
  background: none;
  border: none;
  padding: 5px;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.row-actions button:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--ink);
}
.row-actions button:disabled {
  opacity: 0.4;
}
.row-actions .icon {
  width: 14px;
  height: 14px;
  display: block;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
