<script setup lang="ts">
// «Проверка данных»: противоречия между записями реестра и пробелы, из-за которых листы отчёта выйдут неполными.
// Находки считает сервер (backend/app/services/consistency/engine.py); экран только показывает их и ведёт в раздел, где объект
// исправляют. Ничего не меняется автоматически: какая из двух версий данных верна, решает человек.
import { computed, onMounted } from 'vue'
import { CATEGORY_LABELS, SEVERITY_LABELS, SHEET_LABELS, entitySection } from '../api/consistency'
import DataLoadNotice from '../components/DataLoadNotice.vue'
import ListEmptyRow from '../components/ListEmptyRow.vue'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import PagerNav from '../components/PagerNav.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'
import StatCard from '../components/StatCard.vue'
import { useConsistencyReport } from '../composables/useConsistencyReport'
import { PAGE_SIZE_OPTIONS } from '../utils/pageSize'

const state = useConsistencyReport()
const { filters, report } = state

onMounted(state.load)

const summary = computed(() => report.value?.summary.by_severity ?? {})
const sheetLabel = (sheet: number) => SHEET_LABELS[sheet] ?? `Лист ${sheet}`
const firstShown = computed(() => (state.pageItems.value.length ? (state.page.value - 1) * state.pageSize.value + 1 : 0))
const lastShown = computed(() => (state.page.value - 1) * state.pageSize.value + state.pageItems.value.length)
</script>

<template>
  <div class="consistency-view">
    <div class="stat-row">
      <StatCard :value="report?.total ?? '—'" label="Всего находок" />
      <StatCard :value="summary.error ?? 0" label="Ошибки" tone="warn" />
      <StatCard :value="summary.warning ?? 0" label="Предупреждения" />
      <StatCard :value="summary.info ?? 0" label="Сведения" />
    </div>

    <DataLoadNotice
      v-if="report?.truncated"
      kind="incomplete"
      what="находок"
      :loaded="report.returned"
      :total="report.total"
      hint="Остальные не видны на экране; исправьте показанные и обновите проверку."
    />

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="filters.search" type="text" placeholder="Поиск по объекту и описанию…" aria-label="Поиск по находкам" />
      </div>
      <select v-model="filters.category" class="fbtn" aria-label="Категория">
        <option value="">Категория: все</option>
        <option v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key">{{ label }}</option>
      </select>
      <select v-model="filters.sheet" class="fbtn" aria-label="Лист отчёта">
        <option value="">Лист отчёта: все</option>
        <option v-for="sheet in state.sheets.value" :key="sheet" :value="sheet">{{ sheetLabel(sheet) }}</option>
      </select>
      <select v-model="filters.rule" class="fbtn" aria-label="Правило">
        <option value="">Правило: все</option>
        <option v-for="option in state.ruleOptions.value" :key="option.code" :value="option.code">{{ option.title }}</option>
      </select>
      <div class="chip-group" role="group" aria-label="Важность">
        <button type="button" :class="{ on: filters.severity === 'all' }" @click="filters.severity = 'all'">Все</button>
        <button v-for="(label, key) in SEVERITY_LABELS" :key="key" type="button" :class="{ on: filters.severity === key }" @click="filters.severity = key">
          {{ label }}
        </button>
      </div>
      <div class="spacer"></div>
      <button type="button" class="btn btn-secondary" :disabled="state.loading.value" @click="state.load()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Проверить заново
      </button>
    </div>

    <div class="table-card card">
      <div v-if="state.errorText.value" class="error-banner" role="alert">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        <span>Не удалось выполнить проверку: {{ state.errorText.value }}</span>
        <button type="button" class="btn btn-secondary" :disabled="state.loading.value" @click="state.load()">Повторить</button>
      </div>
      <div v-else-if="!report" class="loading-banner">Проверяем данные…</div>
      <ScrollableTableWrap v-else label="Находки проверки данных">
        <table>
          <thead>
            <tr>
              <th>Важность</th>
              <th>Что проверяли</th>
              <th>Объект</th>
              <th>Описание</th>
              <th>Лист отчёта</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in state.pageItems.value" :key="`${item.rule}:${item.entity_id}:${index}`">
              <td>
                <span class="severity-badge" :class="item.severity">{{ SEVERITY_LABELS[item.severity] }}</span>
              </td>
              <td>
                {{ state.ruleTitle(item.rule) }}
                <div class="category">{{ CATEGORY_LABELS[item.category] }}</div>
              </td>
              <td class="object-cell">
                <router-link
                  v-if="entitySection(item.entity_type)"
                  :to="entitySection(item.entity_type)!.to"
                  :title="`Открыть раздел «${entitySection(item.entity_type)!.label}»`"
                >
                  {{ item.entity_name }}
                </router-link>
                <template v-else>{{ item.entity_name }}</template>
              </td>
              <td class="message-cell">{{ item.message }}</td>
              <td>{{ item.sheet === null ? '—' : sheetLabel(item.sheet) }}</td>
            </tr>
            <!-- Пустой результат — хорошая новость, а не «записей пока нет»: текст другой, кнопки создания нет. -->
            <ListEmptyRow
              v-if="!state.pageItems.value.length"
              :colspan="5"
              :registry-empty="!state.filtersActive.value"
              empty-text="Противоречий и пробелов в данных не найдено."
              @reset="state.resetFilters()"
            />
          </tbody>
        </table>
      </ScrollableTableWrap>
      <div v-if="report" class="table-foot">
        <span>Показано {{ firstShown }}–{{ lastShown }} из {{ state.filtered.value.length }}</span>
        <PageSizeSelect :model-value="state.pageSize.value" :options="[...PAGE_SIZE_OPTIONS]" @update:model-value="state.setPageSize" />
        <PagerNav :page="state.page.value" :page-count="state.pageCount.value" @update:page="state.setPage" />
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
  margin: 14px 0;
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
  min-width: 0;
  text-overflow: ellipsis;
}
.fbtn {
  min-width: 0;
  max-width: 100%;
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
  color: var(--brand-ink);
}
.spacer {
  flex: 1;
}
.severity-badge {
  display: inline-flex;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.severity-badge.error {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.15));
  color: var(--crit-ink);
}
.severity-badge.warning {
  background: var(--status-warn-soft, rgba(232, 163, 61, 0.15));
  color: var(--status-warn);
}
.severity-badge.info {
  color: var(--brand-ink);
  background: var(--brand-soft);
}
.category {
  color: var(--ink-muted);
  font-size: 11px;
}
.object-cell {
  font-weight: 500;
}
.message-cell {
  min-width: 260px;
}
.error-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
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
@media (max-width: 760px) {
  .search-box {
    flex: 1 1 100%;
    min-width: 0;
  }
  .chip-group {
    flex-wrap: wrap;
    gap: 1px;
    background: var(--border);
    max-width: 100%;
  }
  .chip-group button {
    flex: 1 1 auto;
    border-right: none;
  }
}
</style>
