<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useInformationSystemsStore } from '../stores/informationSystems'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'
import { useContainersStore } from '../stores/containers'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { InformationSystem } from '../api/types'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import StatCard from '../components/StatCard.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'
import YesNoStatus from '../components/YesNoStatus.vue'
import InformationSystemFormModal from '../components/InformationSystemFormModal.vue'
// Общая панель фильтров (поиск, селекты, кнопки действий) — UI-10/UI-11.
import '../styles/list-toolbar.css'

const systems = useInformationSystemsStore()
const catalogs = useCatalogsStore()
const devices = useDevicesStore()
const vms = useVMsStore()
const containers = useContainersStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const modalSystem = ref<InformationSystem | null>(null)
// Фикс п.2: "копировать информационную систему для создания на её основе новой".
const copyFromSystem = ref<InformationSystem | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  // devices/vms/containers — не для собственной таблицы этого экрана, а для выпадающих списков
  // источников в ISSourcesListEditor.vue внутри InformationSystemFormModal.vue (тот же приём,
  // что в VMsView.vue: форма читает уже загруженный стор, а не грузит сама).
  await Promise.all([systems.ensureLoaded(), catalogs.ensureLoaded(), devices.ensureLoaded(), vms.ensureLoaded(), containers.ensureLoaded()])
})

watch(
  () => [systems.search, systems.siemFilter],
  () => systems.resetPageOnFilterChange(),
)

function openCreate() {
  modalSystem.value = null
  copyFromSystem.value = null
  modalOpen.value = true
}
function openEdit(s: InformationSystem) {
  modalSystem.value = s
  copyFromSystem.value = null
  modalOpen.value = true
}
function openCopy(s: InformationSystem) {
  modalSystem.value = null
  copyFromSystem.value = s
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalSystem.value = null
  copyFromSystem.value = null
}
async function onSaved() {
  const wasEdit = modalSystem.value !== null
  closeModal()
  await systems.reload()
  notify(wasEdit ? 'Информационная система обновлена' : 'Информационная система добавлена', 'success')
}

async function removeSystem(s: InformationSystem) {
  if (!confirm(`Удалить информационную систему «${s.name}»?`)) return
  deletingId.value = s.id
  try {
    await deleteResource('information-systems', s.id)
    await systems.reload()
    notify('Информационная система удалена', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}

const siemCount = () => systems.all.filter((s) => s.siem_enabled).length
const cryptoCount = () => systems.all.filter((s) => s.crypto_protection_enabled).length
</script>

<template>
  <div class="is-view">
    <div class="stat-row">
      <StatCard :value="systems.all.length" label="Всего информационных систем" />
      <StatCard :value="siemCount()" label="С покрытием SIEM" />
      <StatCard :value="cryptoCount()" label="С применением СКЗИ" />
      <StatCard :value="systems.all.length - siemCount()" label="Без покрытия SIEM" tone="warn" />
    </div>

    <div class="filter-bar list-toolbar">
      <div class="filter-fields">
        <div class="search-box">
          <svg class="icon"><use href="/icons.svg#i-search" /></svg>
          <input
            v-model="systems.search"
            type="text"
            placeholder="Поиск по названию, описанию, IP-адресу…"
            title="Поиск по наименованию, описанию, назначению, IP-адресу"
            aria-label="Поиск по наименованию, описанию, назначению, IP-адресу"
          />
        </div>
        <div class="chip-group">
          <button :class="{ on: systems.siemFilter === 'all' }" @click="systems.siemFilter = 'all'">SIEM: все</button>
          <button :class="{ on: systems.siemFilter === 'yes' }" @click="systems.siemFilter = 'yes'">Да</button>
          <button :class="{ on: systems.siemFilter === 'no' }" @click="systems.siemFilter = 'no'">Нет</button>
        </div>
      </div>

      <div class="filter-actions">
        <button class="btn btn-secondary" :disabled="systems.loading" @click="systems.reload()">
          <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
          Обновить
        </button>
        <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreate">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Добавить ИС
        </button>
      </div>
    </div>

    <div class="table-card card">
      <div v-if="systems.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ systems.error }}
      </div>
      <div v-else-if="systems.loading && !systems.loaded" class="loading-banner">Загрузка реестра информационных систем…</div>
      <ScrollableTableWrap v-else label="Список информационных систем">
        <table>
          <thead>
            <tr>
              <th>Наименование</th>
              <th>Назначение</th>
              <th>IP-адреса</th>
              <th>Организация техподдержки</th>
              <th>SIEM</th>
              <th>СКЗИ</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in systems.pageItems" :key="s.id">
              <td>
                <span class="isname" :title="s.name">{{ s.name }}</span>
                <span v-if="s.description" class="isdesc" :title="s.description">{{ s.description }}</span>
              </td>
              <td class="purpose-cell">
                <span class="clamp-3" :title="s.purpose || undefined">{{ s.purpose || '—' }}</span>
              </td>
              <td class="ip-cell">
                <template v-if="s.ip_addresses?.length">
                  <span v-for="ip in s.ip_addresses" :key="ip" class="ip">{{ ip }}</span>
                </template>
                <template v-else>—</template>
              </td>
              <td>{{ catalogs.label('support-organizations', s.support_organization_id) }}</td>
              <td>
                <YesNoStatus :value="s.siem_enabled" />
              </td>
              <td>
                <YesNoStatus :value="s.crypto_protection_enabled" />
              </td>
              <td>
                <div class="row-actions">
                  <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEdit(s)">
                    <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Копировать" @click="openCopy(s)">
                    <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Удалить" :disabled="deletingId === s.id" @click="removeSystem(s)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <ListEmptyRow
              v-if="!systems.filtered.length"
              :colspan="7"
              :registry-empty="!systems.all.length"
              empty-text="Информационных систем пока нет."
              :action-label="auth.canWrite ? 'Добавить ИС' : undefined"
              @action="openCreate"
              @reset="systems.resetFilters()"
            />
          </tbody>
        </table>
      </ScrollableTableWrap>
      <div class="table-foot">
        <span
          >Показано {{ systems.pageItems.length ? (systems.page - 1) * systems.pageSize + 1 : 0 }}–{{
            (systems.page - 1) * systems.pageSize + systems.pageItems.length
          }}
          из {{ systems.filtered.length }}</span
        >
        <PageSizeSelect :model-value="systems.pageSize" :options="systems.pageSizeOptions" @update:model-value="systems.setPageSize" />
        <div class="pager">
          <button :disabled="systems.page <= 1" @click="systems.setPage(systems.page - 1)">‹</button>
          <button v-for="p in systems.pageCount" :key="p" :class="{ on: p === systems.page }" @click="systems.setPage(p)">{{ p }}</button>
          <button :disabled="systems.page >= systems.pageCount" @click="systems.setPage(systems.page + 1)">›</button>
        </div>
      </div>
    </div>

    <InformationSystemFormModal v-if="modalOpen" :system="modalSystem" :copy-from="copyFromSystem" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 940px;
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
/* Длинные названия, описания и назначения ограничены по высоте (3/2/3 строки): раньше одно «Государственная информационная система
 * автоматизации …» делало строку таблицы выше экрана телефона (UI-06). Полный текст — в title, целиком — в форме записи. */
.isname {
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  max-width: 360px;
  overflow-wrap: anywhere;
}
.isdesc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 11.3px;
  margin-top: 2px;
  max-width: 320px;
}
.purpose-cell {
  color: var(--ink-muted);
  max-width: 260px;
}
.clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.ip-cell {
  color: var(--ink-muted);
  white-space: nowrap;
}
.ip {
  display: block;
  font-family: var(--font-mono);
  font-size: 11.8px;
  color: var(--ink);
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
