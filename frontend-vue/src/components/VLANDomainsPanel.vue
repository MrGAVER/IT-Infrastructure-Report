<script setup lang="ts">
// Панель списка VLAN-доменов — раскрывается кнопкой «Домены VLAN» на VLANsView.vue, тот же
// принцип, что и панель массового назначения рядом. В vanilla-версии домены доступны через
// generic-экран ресурсов (openResource('vlan-domains')) без отдельного дизайна — здесь вместо
// таблицы-в-таблице сделана компактная карточная панель, консистентная с остальным разделом
// VLAN, а не point-by-point копия generic-списка.
import { onMounted, ref } from 'vue'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useDevicesStore } from '../stores/devices'
import { api, deleteResource, listResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { VLANDomain, VLANDomainDeviceLink } from '../api/types'
import VLANDomainFormModal from './VLANDomainFormModal.vue'

const domains = useVLANDomainsStore()
const devicesStore = useDevicesStore()
const { notify, notifyError } = useToast()

const memberCounts = ref<Record<string, number>>({})
const modalDomain = ref<VLANDomain | null>(null)
const modalOpen = ref(false)
const syncingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

async function loadMemberCounts() {
  const links = await listResource<VLANDomainDeviceLink>('vlan-domain-devices', { limit: 1000 })
  const counts: Record<string, number> = {}
  for (const l of links.items) counts[l.domain_id] = (counts[l.domain_id] ?? 0) + 1
  memberCounts.value = counts
}

onMounted(async () => {
  await Promise.all([domains.ensureLoaded(), devicesStore.ensureLoaded(), loadMemberCounts()])
})

function sourceDeviceLabel(d: VLANDomain): string {
  if (!d.source_device_id) return '—'
  const dev = devicesStore.all.find((x) => x.id === d.source_device_id)
  return dev ? dev.system_name || dev.serial_number : d.source_device_id
}

function openCreate() {
  modalDomain.value = null
  modalOpen.value = true
}
function openEdit(d: VLANDomain) {
  modalDomain.value = d
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalDomain.value = null
}
async function onSaved() {
  const wasEdit = modalDomain.value !== null
  closeModal()
  await Promise.all([domains.reload(), loadMemberCounts()])
  notify(wasEdit ? 'Домен обновлён' : 'Домен добавлен', 'success')
}

async function removeDomain(d: VLANDomain) {
  if (!confirm(`Удалить VLAN-домен «${d.name}»?`)) return
  deletingId.value = d.id
  try {
    await deleteResource('vlan-domains', d.id)
    await domains.reload()
    notify('Домен удалён', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}

// Синхронизирует набор VLAN устройства-источника со всеми остальными участниками домена —
// см. POST /api/v1/vlan-domains/{id}/sync (backend/app/api/system.py:sync_vlan_domain).
// Портировано с syncVlanDomain() в frontend/static/vlan.js.
async function syncDomain(d: VLANDomain) {
  syncingId.value = d.id
  try {
    const r = await api.post<{ created_definitions: number; assigned: number }>(`/vlan-domains/${d.id}/sync`, {})
    notify(`VLAN-домен синхронизирован: новых определений — ${r.created_definitions}, назначений — ${r.assigned}`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    syncingId.value = null
  }
}
</script>

<template>
  <div class="domains-panel card">
    <div class="domains-head">
      <b>VLAN-домены</b>
      <button type="button" class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Домен
      </button>
    </div>

    <div v-if="domains.error" class="error-banner">{{ domains.error }}</div>
    <div v-else-if="domains.loading && !domains.loaded" class="empty">Загрузка доменов…</div>
    <div v-else-if="!domains.all.length" class="empty">VLAN-домены не созданы.</div>

    <div v-for="d in domains.all" :key="d.id" class="domain-row">
      <div class="domain-main">
        <b>{{ d.name }}</b>
        <span v-if="d.description" class="domain-desc">{{ d.description }}</span>
        <span class="domain-meta">
          Источник: {{ sourceDeviceLabel(d) }} · Устройств: {{ memberCounts[d.id] ?? 0 }}
          <span v-if="d.auto_sync" class="auto-sync-tag">автосинхронизация</span>
        </span>
      </div>
      <div class="domain-actions">
        <button type="button" class="btn btn-secondary" @click="openEdit(d)">Изменить</button>
        <button
          v-if="d.source_device_id"
          type="button"
          class="btn btn-secondary"
          :disabled="syncingId === d.id"
          @click="syncDomain(d)"
        >
          {{ syncingId === d.id ? 'Синхронизация…' : 'Синхронизировать' }}
        </button>
        <button type="button" class="icon-btn danger" :disabled="deletingId === d.id" aria-label="Удалить домен" @click="removeDomain(d)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </div>

    <VLANDomainFormModal v-if="modalOpen" :domain="modalDomain" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.domains-panel {
  padding: 16px;
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.domains-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.domains-head b {
  font-size: 13px;
}
.empty,
.error-banner {
  font-size: 12.5px;
  color: var(--ink-muted);
  padding: 8px 0;
}
.error-banner {
  color: var(--status-crit);
}
.domain-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
}
.domain-row:first-of-type {
  border-top: none;
}
.domain-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.domain-main b {
  font-size: 13px;
}
.domain-desc {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.domain-meta {
  font-size: 11px;
  color: var(--ink-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.auto-sync-tag {
  font-size: 9.5px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
  background: var(--surface-2);
  border-radius: 20px;
  padding: 1px 7px;
}
.domain-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 640px) {
  .domain-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
