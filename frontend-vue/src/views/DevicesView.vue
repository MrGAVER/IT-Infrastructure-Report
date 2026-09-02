<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Device } from '../api/types'
import StatCard from '../components/StatCard.vue'
import StructuralUnitTree from '../components/StructuralUnitTree.vue'
import DeviceFormModal from '../components/DeviceFormModal.vue'

const devices = useDevicesStore()
const catalogs = useCatalogsStore()
const vlans = useVLANsStore()
const { notify, notifyError } = useToast()

const modalDevice = ref<Device | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  // vlans — не для собственной таблицы этого экрана, а для выпадающего списка VLAN в
  // DeviceVlanListEditor.vue внутри DeviceFormModal.vue (тот же приём, что в
  // InformationSystemsView.vue: форма читает уже загруженный стор, а не грузит сама).
  await Promise.all([devices.ensureLoaded(), catalogs.ensureLoaded(), vlans.ensureLoaded()])
})

watch(
  () => [devices.search, devices.buildingId, devices.deviceTypeId, devices.siemFilter, devices.structuralUnitIds],
  () => devices.resetPageOnFilterChange(),
  { deep: true },
)

function toggleUnit(id: string) {
  const idx = devices.structuralUnitIds.indexOf(id)
  if (idx === -1) devices.structuralUnitIds.push(id)
  else devices.structuralUnitIds.splice(idx, 1)
}

function siemLabel(v: boolean) {
  return v ? 'Да' : 'Нет'
}

function buildingLabel(id: string | null) {
  if (!id) return '—'
  return (catalogs.indexOf('buildings').get(id)?.name as string) ?? '—'
}
function roomLabel(id: string | null) {
  if (!id) return ''
  return (catalogs.indexOf('rooms').get(id)?.name as string) ?? ''
}

const siemCount = () => devices.all.filter((d) => d.siem_enabled).length
const serverTypeName = 'Сервер'

function openCreate() {
  modalDevice.value = null
  modalOpen.value = true
}
function openEdit(d: Device) {
  modalDevice.value = d
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalDevice.value = null
}
async function onSaved(_saved: Device) {
  const wasEdit = modalDevice.value !== null
  closeModal()
  await devices.reload()
  notify(wasEdit ? 'Устройство обновлено' : 'Устройство добавлено', 'success')
}

async function removeDevice(d: Device) {
  const label = d.system_name || d.serial_number
  if (!confirm(`Удалить устройство «${label}»?`)) return
  deletingId.value = d.id
  try {
    await deleteResource('devices', d.id)
    await devices.reload()
    notify('Устройство удалено', 'success')
  } catch (err) {
    // REFERENCED_BY_OTHER_RECORDS и любые другие ошибки удаления одинаково
    // приходят с читаемым message с бэкенда (см. delete_resource) — достаточно
    // показать как есть, без ветвления по коду.
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="devices-view">
    <div class="stat-row">
      <StatCard :value="devices.total" label="Всего устройств" />
      <StatCard :value="devices.all.filter((d) => catalogs.label('device-types', d.device_type_id) === serverTypeName).length" label="Серверы" />
      <StatCard :value="siemCount()" label="С покрытием SIEM" />
      <StatCard :value="devices.total - siemCount()" label="Без покрытия SIEM" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="devices.search" type="text" placeholder="Поиск по имени, серийному №, IP…" />
      </div>

      <select v-model="devices.buildingId" class="fbtn">
        <option value="">Здание: все</option>
        <option v-for="b in catalogs.items['buildings'] ?? []" :key="b.id" :value="b.id">{{ b.name }}</option>
      </select>

      <select v-model="devices.deviceTypeId" class="fbtn">
        <option value="">Тип устройства: все</option>
        <option v-for="t in catalogs.items['device-types'] ?? []" :key="t.id" :value="t.id">{{ t.name }}</option>
      </select>

      <div class="chip-group">
        <button :class="{ on: devices.siemFilter === 'all' }" @click="devices.siemFilter = 'all'">SIEM: все</button>
        <button :class="{ on: devices.siemFilter === 'yes' }" @click="devices.siemFilter = 'yes'">Да</button>
        <button :class="{ on: devices.siemFilter === 'no' }" @click="devices.siemFilter = 'no'">Нет</button>
      </div>

      <details class="tree-pop">
        <summary class="fbtn">
          <svg class="icon"><use href="/icons.svg#i-sitemap" /></svg>
          Структурные подразделения
          <span v-if="devices.structuralUnitIds.length" class="count-badge">{{ devices.structuralUnitIds.length }}</span>
          <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
        </summary>
        <div class="tree-panel">
          <p v-if="!catalogs.structuralUnitTree.length" class="empty-hint">Структурные единицы ещё не заведены в справочнике.</p>
          <StructuralUnitTree
            v-else
            :nodes="catalogs.structuralUnitTree"
            :selected="devices.structuralUnitIds"
            @toggle="toggleUnit"
          />
        </div>
      </details>

      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="devices.loading" @click="devices.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить устройство
      </button>
    </div>

    <div class="table-card card">
      <div v-if="devices.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ devices.error }}
      </div>
      <div v-else-if="devices.loading && !devices.loaded" class="loading-banner">Загрузка реестра устройств…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Тип</th>
              <th>Системное имя</th>
              <th>Серийный №</th>
              <th>Производитель / модель</th>
              <th>ОС</th>
              <th>IP управления</th>
              <th>Здание · помещение</th>
              <th>SIEM</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in devices.pageItems" :key="d.id">
              <td class="type-tag">{{ catalogs.label('device-types', d.device_type_id) }}</td>
              <td>
                <span class="devname">{{ d.system_name || '—' }}</span>
                <span v-if="d.description" class="devmodel">{{ d.description }}</span>
              </td>
              <td class="mono">{{ d.serial_number }}</td>
              <td>{{ [catalogs.label('manufacturers', d.manufacturer_id, ''), catalogs.label('device-models', d.model_id, '')].filter(Boolean).join(' · ') || '—' }}</td>
              <td>{{ d.embedded_os_name || catalogs.label('operating-systems', d.operating_system_id) }}</td>
              <td class="mono">{{ d.management_ips || '—' }}</td>
              <td>{{ [buildingLabel(d.building_id), roomLabel(d.room_id)].filter(Boolean).join(' · ') }}</td>
              <td>
                <span class="status" :class="d.siem_enabled ? 'on' : 'off'">
                  <span class="status-dot"></span>{{ siemLabel(d.siem_enabled) }}
                </span>
              </td>
              <td>
                <div class="row-actions">
                  <button type="button" aria-label="Редактировать" @click="openEdit(d)">
                    <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
                  </button>
                  <button type="button" aria-label="Удалить" :disabled="deletingId === d.id" @click="removeDevice(d)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!devices.filtered.length">
              <td colspan="9" class="empty-row">Ничего не найдено по заданным фильтрам.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span>Показано {{ devices.pageItems.length ? (devices.page - 1) * 6 + 1 : 0 }}–{{ (devices.page - 1) * 6 + devices.pageItems.length }} из {{ devices.filtered.length }}</span>
        <div class="pager">
          <button :disabled="devices.page <= 1" @click="devices.setPage(devices.page - 1)">‹</button>
          <button v-for="p in devices.pageCount" :key="p" :class="{ on: p === devices.page }" @click="devices.setPage(p)">{{ p }}</button>
          <button :disabled="devices.page >= devices.pageCount" @click="devices.setPage(devices.page + 1)">›</button>
        </div>
      </div>
    </div>

    <DeviceFormModal v-if="modalOpen" :device="modalDevice" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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
  min-width: 220px;
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
.fbtn,
select.fbtn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 7px 11px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
  font-weight: 500;
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
.tree-pop {
  position: relative;
}
.tree-pop > summary {
  list-style: none;
  cursor: pointer;
}
.tree-pop > summary::-webkit-details-marker {
  display: none;
}
.count-badge {
  background: var(--brand);
  color: #05161c;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
}
.tree-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 20;
  width: 280px;
  max-height: 320px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px 12px;
  box-shadow: 0 12px 28px -10px rgba(0, 0, 0, 0.5);
}
.empty-hint {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0;
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
  vertical-align: middle;
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
.devmodel {
  display: block;
  color: var(--ink-muted);
  font-size: 11.3px;
  margin-top: 1px;
}
.type-tag {
  color: var(--ink-muted);
  font-size: 12px;
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
