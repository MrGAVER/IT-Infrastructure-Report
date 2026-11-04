<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useContainersStore } from '../stores/containers'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Container } from '../api/types'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import StatCard from '../components/StatCard.vue'
import ContainerFormModal from '../components/ContainerFormModal.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'

const containers = useContainersStore()
const devices = useDevicesStore()
const vms = useVMsStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const modalContainer = ref<Container | null>(null)
// Фикс п.2: "копировать контейнер для создания на его основе нового".
const copyFromContainer = ref<Container | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([containers.ensureLoaded(), devices.ensureLoaded(), vms.ensureLoaded()])
})

// Без сброса страницы поиск оставлял таблицу пустой: список после фильтра короче, а номер страницы
// прежний (тот же дефект и тот же фикс, что в VMsView/DevicesView/InformationSystemsView).
watch(
  () => containers.search,
  () => containers.resetPageOnFilterChange(),
)

function openCreate() {
  modalContainer.value = null
  copyFromContainer.value = null
  modalOpen.value = true
}
function openEdit(c: Container) {
  modalContainer.value = c
  copyFromContainer.value = null
  modalOpen.value = true
}
function openCopy(c: Container) {
  modalContainer.value = null
  copyFromContainer.value = c
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalContainer.value = null
  copyFromContainer.value = null
}
async function onSaved() {
  const wasEdit = modalContainer.value !== null
  closeModal()
  await containers.reload()
  notify(wasEdit ? 'Контейнер обновлён' : 'Контейнер добавлен', 'success')
}

async function removeContainer(c: Container) {
  if (!confirm(`Удалить контейнер «${c.name}»?`)) return
  deletingId.value = c.id
  try {
    await deleteResource('containers', c.id)
    await containers.reload()
    notify('Контейнер удалён', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}

function hostLabel(c: Container): string {
  if (c.virtual_machine_id) {
    const vm = vms.all.find((v) => v.id === c.virtual_machine_id)
    return vm ? `ВМ: ${vm.name}` : '—'
  }
  if (c.physical_device_id) {
    const d = devices.all.find((x) => x.id === c.physical_device_id)
    return d ? `Устройство: ${d.system_name || d.serial_number}` : '—'
  }
  return '—'
}
</script>

<template>
  <div class="containers-view">
    <div class="stat-row">
      <StatCard :value="containers.all.length" label="Всего контейнеров" />
      <StatCard :value="containers.all.filter((c) => c.virtual_machine_id).length" label="На ВМ" />
      <StatCard :value="containers.all.filter((c) => c.physical_device_id).length" label="Напрямую на устройстве" />
      <StatCard :value="containers.all.filter((c) => !c.virtual_machine_id && !c.physical_device_id).length" label="Без указанного размещения" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="containers.search" type="text" placeholder="Поиск по названию, runtime, назначению…" />
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="containers.loading" @click="containers.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить контейнер
      </button>
    </div>

    <div class="table-card card">
      <div v-if="containers.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ containers.error }}
      </div>
      <div v-else-if="containers.loading && !containers.loaded" class="loading-banner">Загрузка контейнеров…</div>
      <ScrollableTableWrap v-else label="Список контейнеров">
        <table>
          <thead>
            <tr>
              <th>Наименование</th>
              <th>Размещение</th>
              <th>Runtime</th>
              <th>Назначение</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in containers.pageItems" :key="c.id">
              <td class="cname">{{ c.name }}</td>
              <td>{{ hostLabel(c) }}</td>
              <td>{{ [c.runtime, c.runtime_version].filter(Boolean).join(' ') || '—' }}</td>
              <td class="purpose-cell">{{ c.purpose || '—' }}</td>
              <td>
                <div class="row-actions">
                  <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEdit(c)">
                    <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Копировать" @click="openCopy(c)">
                    <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Удалить" :disabled="deletingId === c.id" @click="removeContainer(c)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <ListEmptyRow
              v-if="!containers.filtered.length"
              :colspan="5"
              :registry-empty="!containers.all.length"
              empty-text="Контейнеров пока нет."
              :action-label="auth.canWrite ? 'Добавить контейнер' : undefined"
              @action="openCreate"
              @reset="containers.resetFilters()"
            />
          </tbody>
        </table>
      </ScrollableTableWrap>
      <div class="table-foot">
        <span
          >Показано {{ containers.pageItems.length ? (containers.page - 1) * containers.pageSize + 1 : 0 }}–{{
            (containers.page - 1) * containers.pageSize + containers.pageItems.length
          }}
          из {{ containers.filtered.length }}</span
        >
        <PageSizeSelect :model-value="containers.pageSize" :options="containers.pageSizeOptions" @update:model-value="containers.setPageSize" />
        <div class="pager">
          <button :disabled="containers.page <= 1" @click="containers.setPage(containers.page - 1)">‹</button>
          <button v-for="p in containers.pageCount" :key="p" :class="{ on: p === containers.page }" @click="containers.setPage(p)">{{ p }}</button>
          <button :disabled="containers.page >= containers.pageCount" @click="containers.setPage(containers.page + 1)">›</button>
        </div>
      </div>
    </div>

    <ContainerFormModal v-if="modalOpen" :container="modalContainer" :copy-from="copyFromContainer" @close="closeModal" @saved="onSaved" />
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
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
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
.cname {
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
