<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useConnectionsStore } from '../stores/connections'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Connection } from '../api/types'
import { roleLabel } from '../utils/portConfig'
import { debounce } from '../utils/debounce'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import PagerNav from '../components/PagerNav.vue'
import StatCard from '../components/StatCard.vue'
import ConnectionFormModal from '../components/ConnectionFormModal.vue'
import ConnectionCanvasModal from '../components/ConnectionCanvasModal.vue'
import PortConfigReviewModal from '../components/PortConfigReviewModal.vue'
import DevicePortsModal from '../components/DevicePortsModal.vue'

// Таблица — постраничная выборка с сервера (connectionsDashboard); общий кэш (connections) нужен
// формам и схеме — карта занятых портов, см. комментарии в обоих сторах.
const dashboard = useConnectionsDashboardStore()
const connections = useConnectionsStore()
const catalogs = useCatalogsStore()
const devices = useDevicesStore()
const { notify, notifyError } = useToast()

const modalConnection = ref<Connection | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)
// Фикс п.3.4 (батч4): визуальный режим — ДОПОЛНЕНИЕ к стандартной форме "по одному устройству"
// выше, а не замена; см. комментарий в ConnectionCanvasModal.vue про разделение ответственности
// между схемой (выбор пары портов курсором) и ConnectionFormModal.vue (оформление подключения).
const canvasOpen = ref(false)
async function closeCanvas() {
  canvasOpen.value = false
  await dashboard.refreshAfterChange() // подключения, созданные на схеме, должны сразу попасть в таблицу
}

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
  await dashboard.refreshAfterChange()
}

// Проверка ролей портов-соседей (см. services/port_config.py): строка с расхождением/одобрением
// открывает модалку, где расхождение одобряют или устраняют.
const reviewing = ref<Connection | null>(null)
const bulkApproving = ref(false)

// Поиск уходит на сервер, поэтому не на каждую букву. Смена фильтра — сразу и отменяет
// ещё не отправленный поиск: иначе после неё мог бы уйти лишний запрос со старой строкой.
const SEARCH_DEBOUNCE_MS = 300
const searchDebounced = debounce(() => void dashboard.applyFilters(), SEARCH_DEBOUNCE_MS)
watch(() => dashboard.search, () => searchDebounced())
watch(
  () => [dashboard.activeFilter, dashboard.portConfigFilter],
  () => {
    searchDebounced.cancel()
    void dashboard.applyFilters()
  },
)
onBeforeUnmount(() => searchDebounced.cancel())

async function approveAllMatching() {
  const count = dashboard.total
  if (!count) return
  if (!confirm(`Одобрить расхождение ролей портов у ${count} подключ. как допустимое? Одобрение потеряет силу, если роль любого из портов изменится.`)) return
  bulkApproving.value = true
  try {
    const { approved_count } = await dashboard.approveMatching()
    notify(`Одобрено расхождений: ${approved_count}`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    bulkApproving.value = false
  }
}

onMounted(async () => {
  await Promise.all([dashboard.load(), connections.ensureLoaded(), catalogs.ensureLoaded(), devices.ensureLoaded()])
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
  await dashboard.refreshAfterChange()
  notify(wasEdit ? 'Подключение обновлено' : 'Подключение добавлено', 'success')
}

async function removeConnection(c: Connection) {
  if (!confirm(`Удалить подключение «${c.source_device_name} / ${c.source_interface_name} — ${c.destination_device_name} / ${c.destination_interface_name}»?`)) return
  deletingId.value = c.id
  try {
    await deleteResource('connections', c.id)
    await dashboard.refreshAfterChange()
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
      <StatCard :value="dashboard.summary.total" label="Всего подключений" />
      <StatCard :value="dashboard.summary.active" label="Активные" />
      <StatCard :value="dashboard.summary.inactive" label="Неактивные" tone="warn" />
      <StatCard :value="dashboard.summary.mismatch" label="Расхождения портов" tone="warn" />
    </div>

    <div v-if="dashboard.summary.mismatch > 0" class="mismatch-banner" role="status">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
      <span>Найдено подключений с различающимися ролями портов-соседей: {{ dashboard.summary.mismatch }}.</span>
      <button
        v-if="dashboard.portConfigFilter !== 'mismatch'"
        type="button"
        class="btn btn-secondary"
        data-action="show-mismatches"
        @click="dashboard.portConfigFilter = 'mismatch'"
      >
        Показать
      </button>
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="dashboard.search" type="text" placeholder="Поиск по устройству, порту, роли порта…" />
      </div>
      <div class="chip-group">
        <button :class="{ on: dashboard.activeFilter === 'all' }" @click="dashboard.activeFilter = 'all'">Все</button>
        <button :class="{ on: dashboard.activeFilter === 'yes' }" @click="dashboard.activeFilter = 'yes'">Активные</button>
        <button :class="{ on: dashboard.activeFilter === 'no' }" @click="dashboard.activeFilter = 'no'">Неактивные</button>
      </div>
      <div class="chip-group" role="group" aria-label="Проверка ролей портов">
        <button :class="{ on: dashboard.portConfigFilter === 'all' }" @click="dashboard.portConfigFilter = 'all'">Все порты</button>
        <button :class="{ on: dashboard.portConfigFilter === 'mismatch' }" data-filter="mismatch" @click="dashboard.portConfigFilter = 'mismatch'">
          Расхождения ({{ dashboard.summary.mismatch }})
        </button>
        <button :class="{ on: dashboard.portConfigFilter === 'approved' }" data-filter="approved" @click="dashboard.portConfigFilter = 'approved'">
          Одобренные ({{ dashboard.summary.approved }})
        </button>
      </div>
      <button
        v-if="dashboard.portConfigFilter === 'mismatch' && dashboard.total"
        type="button"
        class="btn btn-secondary"
        data-action="approve-all"
        :disabled="bulkApproving"
        @click="approveAllMatching"
      >
        Одобрить все найденные ({{ dashboard.total }})
      </button>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="dashboard.loading" @click="dashboard.refreshAfterChange()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить подключение
      </button>
      <button class="btn btn-secondary" @click="canvasOpen = true">
        <svg class="icon"><use href="/icons.svg#i-sitemap" /></svg>
        Визуальный режим
      </button>
    </div>

    <div class="table-card card">
      <div v-if="dashboard.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ dashboard.error }}
      </div>
      <div v-else-if="dashboard.loading && !dashboard.loaded" class="loading-banner">Загрузка реестра подключений…</div>
      <div v-else class="table-wrap" :class="{ stale: dashboard.loading }">
        <table>
          <thead>
            <tr>
              <th>Источник</th>
              <th></th>
              <th>Назначение</th>
              <th>Тип линии связи</th>
              <th>Роли портов</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in dashboard.items" :key="c.id">
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
              <td class="roles-cell">
                <template v-if="c.port_config_status === 'ok'">{{ roleLabel(c.source_port_role) }}</template>
                <template v-else>
                  <span class="role-line"><span class="mono">{{ c.source_interface_name }}</span>: {{ roleLabel(c.source_port_role) }}</span>
                  <span class="role-line"><span class="mono">{{ c.destination_interface_name }}</span>: {{ roleLabel(c.destination_port_role) }}</span>
                  <button
                    type="button"
                    class="port-badge"
                    :class="c.port_config_status"
                    :aria-label="`Проверить роли портов: ${c.source_device_name} — ${c.destination_device_name}`"
                    @click="reviewing = c"
                  >
                    {{ c.port_config_status === 'mismatch' ? 'Расхождение — проверить' : 'Одобрено' }}
                  </button>
                </template>
              </td>
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
            <tr v-if="!dashboard.items.length">
              <td colspan="7" class="empty-row">Ничего не найдено по заданным фильтрам.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span>Показано {{ dashboard.items.length ? (dashboard.page - 1) * dashboard.pageSize + 1 : 0 }}–{{ (dashboard.page - 1) * dashboard.pageSize + dashboard.items.length }} из {{ dashboard.total }}</span>
        <PageSizeSelect :model-value="dashboard.pageSize" :options="dashboard.pageSizeOptions" @update:model-value="dashboard.setPageSize" />
        <PagerNav :page="dashboard.page" :page-count="dashboard.pageCount" @update:page="dashboard.setPage" />
      </div>
    </div>

    <ConnectionFormModal v-if="modalOpen" :connection="modalConnection" @close="closeModal" @saved="onSaved" />
    <ConnectionCanvasModal v-if="canvasOpen" @close="closeCanvas" />
    <PortConfigReviewModal v-if="reviewing" :connection="reviewing" @close="reviewing = null" />
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
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.mismatch-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  padding: 9px 12px;
  border: 1px solid var(--status-warn);
  border-radius: var(--r-m);
  background: var(--status-warn-soft);
  font-size: 12.5px;
  color: var(--ink);
}
.mismatch-banner .icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
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
  transition: opacity 0.12s;
}
.table-wrap.stale {
  opacity: 0.6;
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
.roles-cell {
  color: var(--ink-muted);
  max-width: 260px;
}
.role-line {
  display: block;
  font-size: 11.8px;
}
.port-badge {
  margin-top: 5px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--surface-2);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-muted);
}
.port-badge.mismatch {
  border-color: var(--status-warn);
  background: var(--status-warn-soft);
  color: var(--ink);
}
.port-badge:hover {
  border-color: var(--brand);
  color: var(--brand);
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
@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
