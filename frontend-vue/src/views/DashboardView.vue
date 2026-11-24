<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import { api } from '../api/client'
import type { DashboardCounts } from '../api/types'
import ReportReadinessCard from '../components/ReportReadinessCard.vue'
import StatCard from '../components/StatCard.vue'

// Карточки сводки: каждое число ведёт на экран, где лежат эти записи. «Программные активы» отдельного экрана
// не имеют — это справочник на экране «Другие справочники», поэтому ссылка сразу открывает его (?catalog=, см. router).
const STAT_CARDS: { key: keyof DashboardCounts; label: string; to: RouteLocationRaw }[] = [
  { key: 'information_systems', label: 'Информационные системы', to: '/information-systems' },
  { key: 'physical_devices', label: 'Физические устройства', to: '/devices' },
  { key: 'virtual_machines', label: 'Виртуальные машины', to: '/vms' },
  { key: 'containers', label: 'Контейнеры', to: '/containers' },
  { key: 'connections', label: 'Подключения', to: '/connections' },
  { key: 'vlan', label: 'VLAN', to: '/vlans' },
  { key: 'software', label: 'Программные активы', to: { path: '/other-catalogs', query: { catalog: 'software-assets' } } },
]

const counts = ref<DashboardCounts | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    counts.value = await api.get<DashboardCounts>('/dashboard')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить сводку'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="dashboard">
    <div v-if="error" class="error-banner card">{{ error }}</div>
    <div v-else-if="loading" class="loading-banner">Загрузка сводки…</div>
    <div v-else-if="counts" class="stat-grid">
      <StatCard v-for="card in STAT_CARDS" :key="card.key" :value="counts[card.key]" :label="card.label" :to="card.to" />
    </div>
    <!-- Блок грузится сам и не зависит от сводки: сбой подсчёта готовности не должен прятать счётчики, и наоборот. -->
    <ReportReadinessCard />
  </div>
</template>

<style scoped>
/* Flex с переносом, а не grid из 4 колонок: карточек 7, и в сетке последний ряд оставался на три четверти пустым.
 * Здесь карточки последнего ряда растягиваются на всю ширину (flex-grow: 1), поэтому «дыры» нет при любом их числе.
 * Базис calc(25% - 12px) даёт ровно 4 карточки в ряд с запасом в один gap на округление; на ≤980px — 2 в ряд. */
.stat-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.stat-grid > * {
  flex: 1 1 calc(25% - 12px);
  min-width: 0;
}
.error-banner {
  padding: 16px;
  color: var(--status-crit);
}
.loading-banner {
  padding: 24px;
  color: var(--ink-muted);
}
@media (max-width: 980px) {
  .stat-grid > * {
    flex-basis: calc(50% - 12px);
  }
}
</style>
