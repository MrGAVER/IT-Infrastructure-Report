<script setup lang="ts">
// Дашборд «Стеки устройств»: по строке на стек — состав, модели, IP управления, расположение и покрытие SIEM; строка
// раскрывается в таблицу участников. Сводка собирается на клиенте из списка стеков и реестра устройств (на устройстве есть
// stack_id и stack_position), отдельного запроса состава по каждому стеку нет — см. utils/stackSummary.ts. Полная форма
// стека (состав, топология, общие VLAN) открывается кнопкой «Открыть».
import { onMounted } from 'vue'
import { useDeviceStacksStore } from '../stores/deviceStacks'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { useDeviceStacksList } from '../composables/useDeviceStacksList'
import { useStackEditor } from '../composables/useStackEditor'
import type { StackSummary } from '../utils/stackSummary'
import { deviceCountLabel } from '../utils/plural'
import DeviceStackFormModal from '../components/DeviceStackFormModal.vue'
import DataLoadNotice from '../components/DataLoadNotice.vue'
import StatCard from '../components/StatCard.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'
import PagedListFooter from '../components/PagedListFooter.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'
import YesNoStatus from '../components/YesNoStatus.vue'
import DeviceStackDetails from '../components/DeviceStackDetails.vue'
// Общая панель фильтров (поиск, кнопки действий) — та же, что у «Устройств», «VLAN», «Подключений».
import '../styles/list-toolbar.css'

const COLUMN_COUNT = 7

const stacks = useDeviceStacksStore()
const devices = useDevicesStore()
const catalogs = useCatalogsStore()
const auth = useAuthStore()
const { notifyError } = useToast()

onMounted(async () => {
  try {
    // Стор стеков при открытии экрана читается заново, а не через ensureLoaded(): стек мог быть создан или изменён в другом
    // месте после первой загрузки, и тогда уже загруженный стор показал бы устаревший список. Пока идёт запрос, на экране
    // остаются прежние данные. Устройства и справочники (для подписей моделей и мест) достаточно загрузить один раз.
    await Promise.all([stacks.reload(), devices.ensureLoaded(), catalogs.ensureLoaded()])
  } catch (err) {
    notifyError(err)
  }
})

// Сводка, поиск, страницы, раскрытие строк и общие VLAN — composables/useDeviceStacksList.ts.
const {
  summaries,
  stats,
  search,
  filtered,
  isSearching,
  page,
  pageSize,
  pageSizeOptions,
  pageCount,
  pageItems,
  total,
  rangeFrom,
  rangeTo,
  setPage,
  setPageSize,
  isExpanded,
  toggle,
  allExpanded,
  toggleAll,
  stackVlans,
} = useDeviceStacksList()

function listText(values: readonly string[]): string {
  return values.join('; ')
}
function siemTitle(s: StackSummary): string {
  return `SIEM: ${s.siemCovered} из ${s.members.length}`
}

// Окно стека, перечитывание и удаление — composables/useStackEditor.ts.
const { modalStack, modalOpen, deletingId, openCreate, openEdit, refresh, closeModal, onSaved, removeStack } = useStackEditor(() => stackVlans.invalidate())
</script>

<template>
  <div class="stacks-view">
    <div class="stat-row">
      <StatCard :value="stats.stacks" label="Стеков" />
      <StatCard :value="stats.devices" label="Устройств в стеках" />
      <StatCard :value="stats.empty" label="Пустых стеков" tone="warn" />
      <StatCard :value="stats.siemIncomplete" label="Стеков без полного SIEM" tone="warn" />
    </div>

    <div class="filter-bar list-toolbar">
      <div class="filter-fields">
        <div class="search-box">
          <svg class="icon"><use href="/icons.svg#i-search" /></svg>
          <input
            v-model="search"
            type="text"
            placeholder="Поиск по стеку, устройству, IP…"
            title="Поиск по названию и описанию стека, имени и серийному номеру устройств, модели, IP управления, расположению"
            aria-label="Поиск по названию и описанию стека, имени и серийному номеру устройств, модели, IP управления, расположению"
          />
        </div>
        <span v-if="isSearching" class="found-count">Найдено {{ total }} из {{ summaries.length }}</span>
      </div>

      <div class="filter-actions">
        <button type="button" class="btn btn-secondary" :disabled="stacks.loading || devices.loading" @click="refresh">
          <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
          Обновить
        </button>
        <button type="button" class="btn btn-secondary" :disabled="!filtered.length" @click="toggleAll">
          {{ allExpanded ? 'Свернуть все' : 'Развернуть все' }}
        </button>
        <button v-if="auth.canWrite" type="button" class="btn btn-primary" @click="openCreate">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Добавить стек
        </button>
      </div>
    </div>

    <div class="table-card card">
      <DataLoadNotice v-if="stacks.truncated" kind="incomplete" what="стеков устройств" :loaded="stacks.all.length" :total="stacks.total" />
      <div v-if="stacks.error || devices.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ stacks.error || devices.error }}
      </div>
      <div v-else-if="(stacks.loading && !stacks.loaded) || (devices.loading && !devices.loaded)" class="loading-banner">Загрузка стеков…</div>
      <ScrollableTableWrap v-else label="Список стеков устройств">
        <table>
          <thead>
            <tr>
              <th>Стек</th>
              <th>Состав</th>
              <th>Производитель / модель</th>
              <th>IP управления</th>
              <th>Здание · помещение</th>
              <th>SIEM</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="s in pageItems" :key="s.stack.id">
              <tr class="stack-row">
                <td class="stack-cell">
                  <button
                    type="button"
                    class="stack-toggle"
                    :aria-expanded="isExpanded(s.stack.id)"
                    :aria-label="`${isExpanded(s.stack.id) ? 'Свернуть' : 'Развернуть'} состав стека «${s.stack.name}»`"
                    @click="toggle(s.stack.id)"
                  >
                    <svg class="icon chev" :class="{ open: isExpanded(s.stack.id) }"><use href="/icons.svg#i-chevd" /></svg>
                    <span class="stack-main">
                      <b class="stack-name" :title="s.stack.name">{{ s.stack.name }}</b>
                      <span v-if="s.stack.description" class="stack-desc" :title="s.stack.description">{{ s.stack.description }}</span>
                    </span>
                  </button>
                </td>
                <td class="nowrap">
                  <span v-if="s.members.length">{{ deviceCountLabel(s.members.length) }}</span>
                  <span v-else class="muted">Пусто</span>
                </td>
                <td>
                  <span class="clip" :title="listText(s.models) || undefined">{{ listText(s.models) || '—' }}</span>
                </td>
                <td class="mono">
                  <span class="clip" :title="listText(s.ips) || undefined">{{ listText(s.ips) || '—' }}</span>
                </td>
                <td>
                  <span class="clip" :title="listText(s.places) || undefined">{{ listText(s.places) || '—' }}</span>
                </td>
                <td class="nowrap">
                  <span v-if="s.siemState === 'empty'" class="muted">—</span>
                  <YesNoStatus v-else-if="s.siemState === 'all'" :value="true" :title="siemTitle(s)" />
                  <YesNoStatus v-else-if="s.siemState === 'none'" :value="false" :title="siemTitle(s)" />
                  <span v-else class="status off" :title="siemTitle(s)"><span class="status-dot"></span>{{ s.siemCovered }} из {{ s.members.length }}</span>
                </td>
                <td class="col-actions">
                  <div class="stack-actions">
                    <button type="button" class="btn btn-secondary" @click="openEdit(s.stack)">Открыть</button>
                    <button
                      v-if="auth.canWrite"
                      type="button"
                      class="icon-btn danger"
                      :disabled="deletingId === s.stack.id"
                      aria-label="Удалить стек"
                      @click="removeStack(s.stack)"
                    >
                      <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="isExpanded(s.stack.id)" class="members-row">
                <td :colspan="COLUMN_COUNT">
                  <DeviceStackDetails :summary="s" :vlans="stackVlans.stateOf(s.stack.id)" @retry="stackVlans.retry(s.stack.id)" />
                </td>
              </tr>
            </template>
            <ListEmptyRow
              v-if="!filtered.length"
              :colspan="COLUMN_COUNT"
              :registry-empty="!stacks.all.length"
              empty-text="Стеки устройств не созданы."
              :action-label="auth.canWrite ? 'Добавить стек' : undefined"
              @action="openCreate"
              @reset="search = ''"
            />
          </tbody>
        </table>
      </ScrollableTableWrap>
      <PagedListFooter
        v-if="filtered.length"
        class="stacks-foot"
        :page="page"
        :page-count="pageCount"
        :page-size="pageSize"
        :page-size-options="pageSizeOptions"
        :range-from="rangeFrom"
        :range-to="rangeTo"
        :total="total"
        @update:page="setPage"
        @update:page-size="setPageSize"
      />
    </div>

    <DeviceStackFormModal v-if="modalOpen" :stack="modalStack" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.found-count {
  font-size: 12px;
  color: var(--ink-muted);
}
.table-card {
  padding: 0;
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
.stacks-foot {
  padding: 10px 14px;
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
tbody tr:last-child > td {
  border-bottom: none;
}
.stack-row:hover > td {
  background: var(--surface-2);
}
.nowrap {
  white-space: nowrap;
}
.muted {
  color: var(--ink-muted);
}
.mono {
  font-family: var(--font-mono, monospace);
}
/* Длинные списки (модели, IP, места нескольких участников) не раздувают строку: одна строка с многоточием, полный текст — в title. */
.clip {
  display: block;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-cell {
  padding: 0;
  min-width: 220px;
}
.stack-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  padding: 11px 14px;
  cursor: pointer;
  text-align: left;
  color: var(--ink);
  font-size: 12.5px;
  font-family: inherit;
}
.stack-toggle .chev {
  flex-shrink: 0;
  color: var(--ink-muted);
  transition: transform 0.15s ease;
}
.stack-toggle .chev.open {
  transform: rotate(180deg);
}
.stack-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.stack-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stack-desc {
  font-size: 11.5px;
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}

.col-actions {
  width: 1%;
  white-space: nowrap;
}
.stack-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

.members-row > td {
  padding: 0 14px 12px 38px;
  background: var(--surface-2);
}
@media (max-width: 860px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
