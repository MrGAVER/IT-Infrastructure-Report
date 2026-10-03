<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useAuditLogStore, ACTION_LABELS } from '../stores/auditLog'
import { useCatalogsStore } from '../stores/catalogs'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import PagerNav from '../components/PagerNav.vue'
import StatCard from '../components/StatCard.vue'
import { debounce } from '../utils/debounce'

const log = useAuditLogStore()
const catalogs = useCatalogsStore()

onMounted(async () => {
  // Журнал только растёт, поэтому при каждом открытии экрана читаем актуальную страницу, а не кэш.
  await Promise.all([log.load(), catalogs.ensureLoaded()])
})

// Поиск уходит на сервер, поэтому не на каждую букву. Смена фильтра — сразу и отменяет ещё не
// отправленный поиск: иначе после неё мог бы уйти лишний запрос со старой строкой.
const SEARCH_DEBOUNCE_MS = 300
const searchDebounced = debounce(() => void log.applyFilters(), SEARCH_DEBOUNCE_MS)
watch(() => log.search, () => searchDebounced())
watch(
  () => [log.actionFilter, log.entityTypeFilter],
  () => {
    searchDebounced.cancel()
    void log.applyFilters()
  },
)
onBeforeUnmount(() => searchDebounced.cancel())

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="audit-view">
    <div class="stat-row">
      <StatCard :value="log.summary.total" label="Всего записей" />
      <StatCard :value="log.countByAction('CREATE')" label="Создано" />
      <StatCard :value="log.countByAction('UPDATE')" label="Изменено" />
      <StatCard :value="log.countByAction('DELETE')" label="Удалено" tone="warn" />
    </div>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="log.search" type="text" placeholder="Поиск по деталям, id записи…" />
      </div>
      <select v-model="log.entityTypeFilter" class="fbtn">
        <option value="">Раздел: все</option>
        <option v-for="key in log.entityTypes" :key="key" :value="key">{{ catalogs.resourceLabel(key) }}</option>
      </select>
      <div class="chip-group">
        <button :class="{ on: log.actionFilter === 'all' }" @click="log.actionFilter = 'all'">Все</button>
        <button v-for="(label, key) in ACTION_LABELS" :key="key" :class="{ on: log.actionFilter === key }" @click="log.actionFilter = key as typeof log.actionFilter">
          {{ label }}
        </button>
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="log.loading" @click="log.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
    </div>

    <div class="table-card card">
      <div v-if="log.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ log.error }}
      </div>
      <div v-else-if="log.loading && !log.loaded" class="loading-banner">Загрузка журнала аудита…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Дата и время</th>
              <th>Раздел</th>
              <th>Действие</th>
              <th>ID записи</th>
              <th>Детали</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in log.items" :key="e.id">
              <td class="mono when-cell">{{ formatWhen(e.created_at) }}</td>
              <td>{{ catalogs.resourceLabel(e.entity_type) }}</td>
              <td>
                <span class="action-badge" :class="e.action.toLowerCase()">{{ ACTION_LABELS[e.action] ?? e.action }}</span>
              </td>
              <td class="mono id-cell" :title="e.entity_id">{{ e.entity_id.slice(0, 8) }}…</td>
              <td class="details-cell">{{ e.details || '—' }}</td>
            </tr>
            <tr v-if="!log.items.length">
              <td colspan="5" class="empty-row">Ничего не найдено по заданным фильтрам.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span>Показано {{ log.items.length ? (log.page - 1) * log.pageSize + 1 : 0 }}–{{ (log.page - 1) * log.pageSize + log.items.length }} из {{ log.total }}</span>
        <PageSizeSelect :model-value="log.pageSize" :options="log.pageSizeOptions" @update:model-value="log.setPageSize" />
        <PagerNav :page="log.page" :page-count="log.pageCount" @update:page="log.setPage" />
      </div>
    </div>
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
.fbtn {
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
  white-space: nowrap;
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
  min-width: 780px;
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
  padding: 10px 14px;
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
.when-cell {
  white-space: nowrap;
  color: var(--ink-muted);
}
.id-cell {
  color: var(--ink-muted);
  cursor: help;
}
.details-cell {
  color: var(--ink-muted);
  max-width: 340px;
}
.action-badge {
  display: inline-flex;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}
.action-badge.create {
  background: var(--status-ok-soft, rgba(51, 201, 167, 0.15));
  color: var(--status-ok);
}
.action-badge.update {
  color: var(--brand);
  background: var(--brand-soft);
}
.action-badge.delete {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.15));
  color: var(--status-crit);
}
.action-badge.sync {
  background: var(--status-warn-soft, rgba(232, 163, 61, 0.15));
  color: var(--status-warn);
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
@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
