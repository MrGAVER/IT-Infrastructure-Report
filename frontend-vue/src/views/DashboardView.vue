<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import { api } from '../api/client'
import type { DashboardCounts } from '../api/types'
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
    <p class="note">
      Полная функциональность («Диспетчерская», Vue 3 + TypeScript) пока реализована для раздела
      «Инвентаризация устройств» — см. меню слева. Остальные разделы будут переноситься поэтапно.
    </p>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.error-banner {
  padding: 16px;
  color: var(--status-crit);
}
.loading-banner {
  padding: 24px;
  color: var(--ink-muted);
}
.note {
  margin-top: 20px;
  font-size: 12px;
  color: var(--ink-muted);
  max-width: 60ch;
  line-height: 1.6;
}
@media (max-width: 980px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
