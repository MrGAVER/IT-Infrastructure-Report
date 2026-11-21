<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useConnectionsStore } from '../stores/connections'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import { useConnectionPortDialogs } from '../composables/useConnectionPortDialogs'
import type { Connection } from '../api/types'
import { debounce } from '../utils/debounce'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import PagerNav from '../components/PagerNav.vue'
import PortSyncPlanModal from '../components/PortSyncPlanModal.vue'
import StatCard from '../components/StatCard.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'
import ConnectionTableRow from '../components/ConnectionTableRow.vue'
import ConnectionFormModal from '../components/ConnectionFormModal.vue'
import ConnectionCanvasModal from '../components/ConnectionCanvasModal.vue'
import PortConfigReviewModal from '../components/PortConfigReviewModal.vue'
import PortConfigEditModal from '../components/PortConfigEditModal.vue'
import DevicePortsModal from '../components/DevicePortsModal.vue'
// Общая панель фильтров (поиск, селекты, кнопки действий) — UI-10/UI-11.
import '../styles/list-toolbar.css'

// Таблица — постраничная выборка с сервера (connectionsDashboard); общий кэш (connections) нужен
// формам и схеме — карта занятых портов, см. комментарии в обоих сторах.
const dashboard = useConnectionsDashboardStore()
const connections = useConnectionsStore()
const catalogs = useCatalogsStore()
const devices = useDevicesStore()
const auth = useAuthStore()
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

// Окна портов устройства, проверки расхождения, правки порта и плана согласования — composables/useConnectionPortDialogs.ts.
const {
  portsTarget,
  openPortsForInterface,
  closePorts,
  onPortsSaved,
  reviewing,
  syncPlanOpen,
  manageFromReview,
  editing,
  editPort,
  editPortFromReview,
  manageFromEdit,
} = useConnectionPortDialogs()
const bulkApproving = ref(false)

// Поиск уходит на сервер, поэтому не на каждую букву. Смена фильтра — сразу и отменяет
// ещё не отправленный поиск: иначе после неё мог бы уйти лишний запрос со старой строкой.
const SEARCH_DEBOUNCE_MS = 300
const searchDebounced = debounce(() => void dashboard.applyFilters(), SEARCH_DEBOUNCE_MS)
watch(
  () => dashboard.search,
  () => searchDebounced(),
)
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
  if (
    !confirm(
      `Одобрить расхождение конфигурации портов у ${count} подключ. как допустимое? Одобрение потеряет силу, если роль, режим или VLAN любого из портов изменятся.`,
    )
  )
    return
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
  if (!confirm(`Удалить подключение «${c.source_device_name} / ${c.source_interface_name} — ${c.destination_device_name} / ${c.destination_interface_name}»?`))
    return
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
      <span>Найдено подключений с различающейся конфигурацией портов-соседей (роль, режим, VLAN): {{ dashboard.summary.mismatch }}.</span>
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

    <div class="filter-bar list-toolbar">
      <div class="filter-fields">
        <div class="search-box">
          <svg class="icon"><use href="/icons.svg#i-search" /></svg>
          <input
            v-model="dashboard.search"
            type="text"
            placeholder="Поиск по устройству, порту, роли…"
            title="Поиск по устройству, порту, роли, режиму порта"
            aria-label="Поиск по устройству, порту, роли, режиму порта"
          />
        </div>
        <div class="chip-group">
          <button :class="{ on: dashboard.activeFilter === 'all' }" @click="dashboard.activeFilter = 'all'">Все</button>
          <button :class="{ on: dashboard.activeFilter === 'yes' }" @click="dashboard.activeFilter = 'yes'">Активные</button>
          <button :class="{ on: dashboard.activeFilter === 'no' }" @click="dashboard.activeFilter = 'no'">Неактивные</button>
        </div>
        <div class="chip-group" role="group" aria-label="Проверка конфигурации портов">
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
        <button v-if="dashboard.summary.mismatch" type="button" class="btn btn-secondary" data-action="sync-by-rules" @click="syncPlanOpen = true">
          Согласовать по правилам…
        </button>
      </div>

      <!-- Кнопка схемы — в группе действий справа, а не отдельным элементом панели: перенос выбрасывал её одну на вторую строку (UI-11). -->
      <div class="filter-actions">
        <button class="btn btn-secondary" :disabled="dashboard.loading" @click="dashboard.refreshAfterChange()">
          <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
          Обновить
        </button>
        <button class="btn btn-secondary" @click="canvasOpen = true">
          <svg class="icon"><use href="/icons.svg#i-sitemap" /></svg>
          Визуальный режим
        </button>
        <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreate">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Добавить подключение
        </button>
      </div>
    </div>

    <div class="table-card card">
      <div v-if="dashboard.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ dashboard.error }}
      </div>
      <div v-else-if="dashboard.loading && !dashboard.loaded" class="loading-banner">Загрузка реестра подключений…</div>
      <ScrollableTableWrap v-else label="Список подключений" :class="{ stale: dashboard.loading }">
        <table>
          <thead>
            <tr>
              <th>Источник</th>
              <th></th>
              <th>Назначение</th>
              <th>Тип линии связи</th>
              <th>Конфигурация портов</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <ConnectionTableRow
              v-for="c in dashboard.items"
              :key="c.id"
              :connection="c"
              :can-write="auth.canWrite"
              :deleting="deletingId === c.id"
              @edit-port="editPort(c, $event)"
              @manage-ports="openPortsForInterface"
              @review="reviewing = c"
              @open="openEdit(c)"
              @remove="removeConnection(c)"
            />
            <!-- «Реестр пуст» — по итогам всего реестра (summary), а не по текущей странице: на ней пусто и тогда, когда фильтр ничего не оставил. -->
            <ListEmptyRow
              v-if="!dashboard.items.length"
              :colspan="7"
              :registry-empty="!dashboard.summary.total"
              empty-text="Подключений пока нет."
              :action-label="auth.canWrite ? 'Добавить подключение' : undefined"
              @action="openCreate"
              @reset="dashboard.resetFilters()"
            />
          </tbody>
        </table>
      </ScrollableTableWrap>
      <div class="table-foot">
        <span
          >Показано {{ dashboard.items.length ? (dashboard.page - 1) * dashboard.pageSize + 1 : 0 }}–{{
            (dashboard.page - 1) * dashboard.pageSize + dashboard.items.length
          }}
          из {{ dashboard.total }}</span
        >
        <PageSizeSelect :model-value="dashboard.pageSize" :options="dashboard.pageSizeOptions" @update:model-value="dashboard.setPageSize" />
        <PagerNav :page="dashboard.page" :page-count="dashboard.pageCount" @update:page="dashboard.setPage" />
      </div>
    </div>

    <ConnectionFormModal v-if="modalOpen" :connection="modalConnection" @close="closeModal" @saved="onSaved" />
    <ConnectionCanvasModal v-if="canvasOpen" @close="closeCanvas" />
    <PortSyncPlanModal
      v-if="syncPlanOpen"
      :scope="{}"
      title="Согласование портов по правилам"
      @close="syncPlanOpen = false"
      @applied="dashboard.refreshAfterChange()"
    />
    <PortConfigReviewModal
      v-if="reviewing"
      :connection="reviewing"
      @close="reviewing = null"
      @manage-ports="manageFromReview"
      @edit-port="editPortFromReview"
    />
    <PortConfigEditModal
      v-if="editing"
      :connection="editing.connection"
      :side="editing.side"
      @close="editing = null"
      @saved="editing = null"
      @manage-ports="manageFromEdit"
    />
    <DevicePortsModal v-if="portsTarget" :device-id="portsTarget.deviceId" :device-label="portsTarget.deviceLabel" @close="closePorts" @saved="onPortsSaved" />
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
.table-wrap {
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
tbody :deep(td) {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: top;
}
tbody :deep(tr:last-child td) {
  border-bottom: none;
}
tbody :deep(tr:hover td) {
  background: var(--surface-2);
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
@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
