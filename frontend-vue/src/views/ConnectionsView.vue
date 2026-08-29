<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useConnectionsStore } from '../stores/connections'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Connection } from '../api/types'
import StatCard from '../components/StatCard.vue'
import ConnectionFormModal from '../components/ConnectionFormModal.vue'
import DevicePortsModal from '../components/DevicePortsModal.vue'

const connections = useConnectionsStore()
const catalogs = useCatalogsStore()
const devices = useDevicesStore()
const { notify, notifyError } = useToast()

const modalConnection = ref<Connection | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

// Прямое управление портами устройства из строки таблицы — без захода в форму подключения
// (см. DevicePortsModal.vue). Connection отдаёт только *_interface_id и уже резолвленные
// *_name (enrich_connections() на бэкенде), без physical_device_id напрямую — id устройства
// находим через уже загруженный каталог 'interfaces' (ConnectionsView грузит его в onMounted).
const portsTarget = ref<{ deviceId: string; deviceLabel: string } | null>(null)
function openPortsForInterface(interfaceId: string, deviceLabel: string) {
  const deviceId = catalogs.indexOf('interfaces').get(interfaceId)?.physical_device_id as string | undefined
  if (!deviceId) return
  portsTarget.value = { deviceId, deviceLabel }
}
function closePorts() {
  portsTarget.value = null
}
async function onPortsSaved() {
  closePorts()
  // Переименование/добавление порта могло изменить то, что показывает таблица
  // (source_interface_name/destination_interface_name резолвятся один раз при загрузке
  // подключений), поэтому перечитываем список — тот же принцип, что onSaved() ниже.
  await connections.reload()
}

onMounted(async () => {
  await Promise.all([connections.ensureLoaded(), catalogs.ensureLoaded(), devices.ensureLoaded()])
})

function openCreate() {
  modalConnection.value = null
  modalOpen.value = true
}
function openEdit(c: Connection) {
  modalConnection.value = c
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalConnection.value = null
}
async function onSaved() {
  const wasEdit = modalConnection.value !== null
  closeModal()
  await connections.reload()
  notify(wasEdit ? 'Подключение обновлено' : 'Подключение добавлено', 'success')
}

async function removeConnection(c: Connection) {
  if (!confirm(`Удалить подключение «${c.source_device_name} / ${c.source_interface_name} — ${c.destination_device_name} / ${c.destination_interface_name}»?`)) return
  deletingId.value = c.id
  try {
    await deleteResource('connections', c.id)
    await connections.reload()
    notify('Подключение удалено', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="connections-view">
    <div class="stat-row">
      <StatCard :value="connections.total" label="Всего подключений" />
      <StatCard :value="connections.all.filter((c) => c.is_active).length" label="Активные" />
      <StatCard :value="connections.all.filter((c) => !c.is_active).length" label="Неактивные" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="connections.search" type="text" placeholder="Поиск по устройству, порту, назначению…" />
      </div>
      <div class="chip-group">
        <button :class="{ on: connections.activeFilter === 'all' }" @click="connections.activeFilter = 'all'">Все</button>
        <button :class="{ on: connections.activeFilter === 'yes' }" @click="connections.activeFilter = 'yes'">Активные</button>
        <button :class="{ on: connections.activeFilter === 'no' }" @click="connections.activeFilter = 'no'">Неактивные</button>
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="connections.loading" @click="connections.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить подключение
      </button>
    </div>

    <div class="table-card card">
      <div v-if="connections.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ connections.error }}
      </div>
      <div v-else-if="connections.loading && !connections.loaded" class="loading-banner">Загрузка реестра подключений…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Источник</th>
              <th></th>
              <th>Назначение</th>
              <th>Тип линии связи</th>
              <th>Назначение линии</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in connections.pageItems" :key="c.id">
              <td>
                <span class="devname">{{ c.source_device_name }}</span>
                <span class="portname mono">
                  {{ c.source_interface_name }}
                  <button type="button" class="port-manage-btn" aria-label="Управлять портами исходного устройства" title="Управлять портами устройства" @click="openPortsForInterface(c.source_interface_id, c.source_device_name)">
                    <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
                  </button>
                </span>
              </td>
              <td class="link-cell"><svg class="icon"><use href="/icons.svg#i-network" /></svg></td>
              <td>
                <span class="devname">{{ c.destination_device_name }}</span>
                <span class="portname mono">
                  {{ c.destination_interface_name }}
                  <button type="button" class="port-manage-btn" aria-label="Управлять портами конечного устройства" title="Управлять портами устройства" @click="openPortsForInterface(c.destination_interface_id, c.destination_device_name)">
                    <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
                  </button>
                </span>
              </td>
              <td>{{ c.connection_type_name }}</td>
              <td class="purpose-cell">{{ c.purpose || '—' }}</td>
              <td>
                <span class="status" :class="c.is_active ? 'on' : 'off'">
                  <span class="status-dot"></span>{{ c.is_active ? 'Активно' : 'Неактивно' }}
                </span>
              </td>
              <td>
                <div class="row-actions">
                  <button type="button" aria-label="Редактировать" @click="openEdit(c)">
                    <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
                  </button>
                  <button type="button" aria-label="Удалить" :disabled="deletingId === c.id" @click="removeConnection(c)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!connections.filtered.length">
              <td colspan="7" class="empty-row">Ничего не найдено по заданным фильтрам.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span>Показано {{ connections.pageItems.length ? (connections.page - 1) * 8 + 1 : 0 }}–{{ (connections.page - 1) * 8 + connections.pageItems.length }} из {{ connections.filtered.length }}</span>
        <div class="pager">
          <button :disabled="connections.page <= 1" @click="connections.setPage(connections.page - 1)">‹</button>
          <button v-for="p in connections.pageCount" :key="p" :class="{ on: p === connections.page }" @click="connections.setPage(p)">{{ p }}</button>
          <button :disabled="connections.page >= connections.pageCount" @click="connections.setPage(connections.page + 1)">›</button>
        </div>
      </div>
    </div>

    <ConnectionFormModal v-if="modalOpen" :connection="modalConnection" @close="closeModal" @saved="onSaved" />
    <DevicePortsModal
      v-if="portsTarget"
      :device-id="portsTarget.deviceId"
      :device-label="portsTarget.deviceLabel"
      @close="closePorts"
      @saved="onPortsSaved"
    />
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
  min-width: 240px;
  max-width: 380px;
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
.chip-group {
  display: flex;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
}
.chip-group button {
  border: none;
  background: var(--surface);
  padding: 7px 11px;
  font-size: 12px;
  color: var(--ink-muted);
  font-weight: 500;
  border-right: 1px solid var(--border);
}
.chip-group button:last-child {
  border-right: none;
}
.chip-group button.on {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 700;
}
.spacer {
  flex: 1;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 880px;
}
thead th {
  text-align: left;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  font-weight: 600;
  white-space: nowrap;
}
tbody td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: top;
}
tbody tr:last-child td {
  border-bottom: none;
}
tbody tr:hover td {
  background: var(--surface-2);
}
.devname {
  font-weight: 600;
  display: block;
}
.portname {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--ink-muted);
  font-size: 11.3px;
  margin-top: 2px;
}
.port-manage-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  background: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
  opacity: 0;
  transition: opacity 0.1s;
}
tr:hover .port-manage-btn {
  opacity: 1;
}
.port-manage-btn:hover {
  color: var(--brand);
  background: var(--surface-2);
}
.port-manage-btn .icon {
  width: 11px;
  height: 11px;
}
.link-cell {
  text-align: center;
  color: var(--ink-muted);
}
.link-cell .icon {
  width: 14px;
  height: 14px;
}
.purpose-cell {
  color: var(--ink-muted);
  max-width: 200px;
}
.empty-row {
  text-align: center;
  color: var(--ink-muted);
  padding: 26px 14px;
}
.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px;
  color: var(--status-crit);
  font-size: 13px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.row-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
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
.table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px;
  font-size: 11.5px;
  color: var(--ink-muted);
  gap: 12px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  gap: 4px;
}
.pager button {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--r-s);
  width: 26px;
  height: 26px;
  color: var(--ink-muted);
}
.pager button.on {
  background: var(--brand);
  color: #05161c;
  border-color: var(--brand);
}
.pager button:disabled {
  opacity: 0.4;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
