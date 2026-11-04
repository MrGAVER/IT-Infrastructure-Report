<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useVMsStore } from '../stores/vms'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useInformationSystemsStore } from '../stores/informationSystems'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { VirtualMachine } from '../api/types'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import StatCard from '../components/StatCard.vue'
import VMFormModal from '../components/VMFormModal.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'

const vms = useVMsStore()
const catalogs = useCatalogsStore()
const devices = useDevicesStore()
const informationSystems = useInformationSystemsStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const modalVM = ref<VirtualMachine | null>(null)
// Фикс п.2: "копировать виртуальную машину для создания на его основе новой".
const copyFromVM = ref<VirtualMachine | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([vms.ensureLoaded(), catalogs.ensureLoaded(), devices.ensureLoaded()])
})

// Без сброса страницы поиск «ломался»: если пользователь был на 2-й странице и вводил запрос,
// отфильтрованный список укорачивался, а store.page оставался прежним — pageItems выходил за
// границы и таблица была пустой без сообщения «Ничего не найдено» (найденные ВМ лежали на
// странице 1). Тот же приём, что в DevicesView/InformationSystemsView/AuditLogView.
watch(
  () => vms.search,
  () => vms.resetPageOnFilterChange(),
)

function openCreate() {
  modalVM.value = null
  copyFromVM.value = null
  modalOpen.value = true
}
function openEdit(vm: VirtualMachine) {
  modalVM.value = vm
  copyFromVM.value = null
  modalOpen.value = true
}
function openCopy(vm: VirtualMachine) {
  modalVM.value = null
  copyFromVM.value = vm
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalVM.value = null
  copyFromVM.value = null
}
async function onSaved() {
  const wasEdit = modalVM.value !== null
  closeModal()
  // В списке ИС показаны IP-адреса связанных ВМ — после правки ВМ он устарел и откроется загрузкой заново.
  informationSystems.invalidate()
  await vms.reload()
  notify(wasEdit ? 'Виртуальная машина обновлена' : 'Виртуальная машина добавлена', 'success')
}

async function removeVM(vm: VirtualMachine) {
  if (!confirm(`Удалить виртуальную машину «${vm.name}»?`)) return
  deletingId.value = vm.id
  try {
    await deleteResource('vms', vm.id)
    await vms.reload()
    notify('Виртуальная машина удалена', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}

function hostLabel(id: string | null) {
  if (!id) return '—'
  const host = devices.all.find((d) => d.id === id)
  return host ? host.system_name || host.serial_number : '—'
}
</script>

<template>
  <div class="vms-view">
    <div class="stat-row">
      <StatCard :value="vms.total" label="Всего виртуальных машин" />
      <StatCard :value="vms.all.filter((v) => v.physical_device_id).length" label="Размещены на хосте" />
      <StatCard :value="vms.all.filter((v) => !v.physical_device_id).length" label="Без указанного хоста" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="vms.search" type="text" placeholder="Поиск по названию, назначению…" />
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="vms.loading" @click="vms.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить ВМ
      </button>
    </div>

    <div class="table-card card">
      <div v-if="vms.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ vms.error }}
      </div>
      <div v-else-if="vms.loading && !vms.loaded" class="loading-banner">Загрузка реестра виртуальных машин…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Операционная система</th>
              <th>Хост (физическое устройство)</th>
              <th>Гипервизор</th>
              <th>Целевое назначение</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="vm in vms.pageItems" :key="vm.id">
              <td class="vmname">{{ vm.name }}</td>
              <td>{{ catalogs.label('operating-systems', vm.operating_system_id) }}</td>
              <td>{{ hostLabel(vm.physical_device_id) }}</td>
              <td>{{ catalogs.label('operating-systems', vm.hypervisor_os_id) }}</td>
              <td class="purpose-cell">{{ vm.purpose || '—' }}</td>
              <td>
                <div class="row-actions">
                  <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEdit(vm)">
                    <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Копировать" @click="openCopy(vm)">
                    <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Удалить" :disabled="deletingId === vm.id" @click="removeVM(vm)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <ListEmptyRow
              v-if="!vms.filtered.length"
              :colspan="6"
              :registry-empty="!vms.all.length"
              empty-text="Виртуальных машин пока нет."
              :action-label="auth.canWrite ? 'Добавить ВМ' : undefined"
              @action="openCreate"
              @reset="vms.resetFilters()"
            />
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span
          >Показано {{ vms.pageItems.length ? (vms.page - 1) * vms.pageSize + 1 : 0 }}–{{ (vms.page - 1) * vms.pageSize + vms.pageItems.length }} из
          {{ vms.filtered.length }}</span
        >
        <PageSizeSelect :model-value="vms.pageSize" :options="vms.pageSizeOptions" @update:model-value="vms.setPageSize" />
        <div class="pager">
          <button :disabled="vms.page <= 1" @click="vms.setPage(vms.page - 1)">‹</button>
          <button v-for="p in vms.pageCount" :key="p" :class="{ on: p === vms.page }" @click="vms.setPage(p)">{{ p }}</button>
          <button :disabled="vms.page >= vms.pageCount" @click="vms.setPage(vms.page + 1)">›</button>
        </div>
      </div>
    </div>

    <VMFormModal v-if="modalOpen" :vm="modalVM" :copy-from="copyFromVM" @close="closeModal" @saved="onSaved" />
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
  min-width: 0;
  /* Длинный плейсхолдер/запрос обрезается многоточием, а не посреди буквы. */
  text-overflow: ellipsis;
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
  min-width: 820px;
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
.vmname {
  font-weight: 600;
}
.purpose-cell {
  color: var(--ink-muted);
  max-width: 260px;
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
/* Телефон (то же ≤760px, что у мобильного меню): поиск занимает всю строку, чтобы плейсхолдер помещался. */
@media (max-width: 760px) {
  .search-box {
    flex: 1 1 100%;
    min-width: 0;
  }
}
</style>
