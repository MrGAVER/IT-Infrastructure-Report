<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import ToastHost from '../components/ToastHost.vue'

const sidebarOpen = ref(false)
const route = useRoute()

const titles: Record<string, { title: string; crumb: string }> = {
  dashboard: { title: 'Дашборд', crumb: 'Обзор' },
  'information-systems': { title: 'Информационные системы', crumb: 'Лист 1 · Информационные системы' },
  devices: { title: 'Инвентаризация физических устройств', crumb: 'Инвентаризация › Физические устройства' },
  connections: { title: 'Подключения', crumb: 'Лист 3 · Подключения' },
  vlans: { title: 'VLAN', crumb: 'Справочники · VLAN' },
  buildings: { title: 'Здания и помещения', crumb: 'Справочники · Здания и помещения' },
  'structural-units': { title: 'Структурные подразделения', crumb: 'Справочники · Структурные подразделения' },
  vms: { title: 'Виртуальные машины', crumb: 'Лист 4 · Виртуальные машины' },
  reports: { title: 'Отчёты', crumb: 'Система · Отчёты' },
  'report-templates': { title: 'Шаблоны отчётов', crumb: 'Система · Отчёты · Шаблоны' },
  'report-template-editor': { title: 'Редактор шаблона', crumb: 'Система · Отчёты · Шаблоны · Редактор' },
  'report-template-editor-docx': { title: 'Редактор шаблона', crumb: 'Система · Отчёты · Шаблоны · Редактор' },
  'audit-log': { title: 'Журнал аудита', crumb: 'Система · Журнал аудита' },
  settings: { title: 'Настройки', crumb: 'Система › Настройки' },
}
const heading = computed(
  () =>
    titles[route.name as string] ?? {
      title: (route.meta.title as string) ?? String(route.name ?? ''),
      crumb: '',
    },
)
</script>

<template>
  <div class="app-shell">
    <Sidebar :open="sidebarOpen" @close="sidebarOpen = false" />
    <div class="main">
      <Topbar :title="heading.title" :crumb="heading.crumb" @toggle-sidebar="sidebarOpen = true" />
      <div class="content">
        <router-view />
      </div>
    </div>
    <ToastHost />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.content {
  padding: 18px 20px 32px;
  overflow: auto;
}
</style>
