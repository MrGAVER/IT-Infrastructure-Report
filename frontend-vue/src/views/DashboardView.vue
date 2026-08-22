<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { DashboardCounts } from '../api/types'
import StatCard from '../components/StatCard.vue'

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
      <StatCard :value="counts.information_systems" label="Информационные системы" />
      <StatCard :value="counts.physical_devices" label="Физические устройства" />
      <StatCard :value="counts.virtual_machines" label="Виртуальные машины" />
      <StatCard :value="counts.containers" label="Контейнеры" />
      <StatCard :value="counts.connections" label="Подключения" />
      <StatCard :value="counts.vlan" label="VLAN" />
      <StatCard :value="counts.software" label="Программные активы" />
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
