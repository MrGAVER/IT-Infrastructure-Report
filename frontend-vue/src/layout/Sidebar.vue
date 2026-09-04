<script setup lang="ts">
import { useOrganizationStore } from '../stores/organization'

defineProps<{ open: boolean }>()
defineEmits<{ close: [] }>()

const organization = useOrganizationStore()

const primaryNav = [
  { to: '/dashboard', icon: 'i-home', label: 'Дашборд' },
  { to: '/information-systems', icon: 'i-layers', label: 'Информационные системы' },
  { to: '/devices', icon: 'i-server', label: 'Инвентаризация устройств' },
  { to: '/connections', icon: 'i-network', label: 'Подключения' },
  { to: '/vms', icon: 'i-box', label: 'Виртуальные машины' },
  { to: '/containers', icon: 'i-box', label: 'Контейнеры' },
]
const catalogNav = [
  { to: '/vlans', icon: 'i-grid', label: 'VLAN' },
  { to: '/buildings', icon: 'i-building', label: 'Здания и помещения' },
  { to: '/structural-units', icon: 'i-sitemap', label: 'Структурные подразделения' },
  { to: '/other-catalogs', icon: 'i-layers', label: 'Другие справочники' },
]
const systemNav = [
  { to: '/reports', icon: 'i-file', label: 'Отчёты' },
  { to: '/report-templates', icon: 'i-layers', label: 'Шаблоны отчётов' },
  { to: '/audit-log', icon: 'i-activity', label: 'Журнал аудита' },
]
</script>

<template>
  <aside class="sidebar" :class="{ open }">
    <div class="brand">
      <div class="brand-mark">ITR</div>
      <div class="brand-text">
        Реестр ИТ-инфраструктуры
        <span>{{ organization.name }}</span>
      </div>
    </div>

    <div class="nav-group-label">Регламентный отчёт</div>
    <ul class="nav">
      <li v-for="item in primaryNav" :key="item.to">
        <router-link :to="item.to" @click="$emit('close')">
          <svg class="icon"><use :href="`/icons.svg#${item.icon}`" /></svg>
          {{ item.label }}
        </router-link>
      </li>
    </ul>

    <div class="nav-group-label">Справочники</div>
    <ul class="nav">
      <li v-for="item in catalogNav" :key="item.to">
        <router-link :to="item.to" @click="$emit('close')">
          <svg class="icon"><use :href="`/icons.svg#${item.icon}`" /></svg>
          {{ item.label }}
        </router-link>
      </li>
    </ul>

    <div class="nav-group-label">Система</div>
    <ul class="nav">
      <li v-for="item in systemNav" :key="item.to">
        <router-link :to="item.to" @click="$emit('close')">
          <svg class="icon"><use :href="`/icons.svg#${item.icon}`" /></svg>
          {{ item.label }}
        </router-link>
      </li>
    </ul>

    <div class="sidebar-foot">
      <ul class="nav">
        <li>
          <router-link to="/settings" @click="$emit('close')">
            <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
            Настройки
          </router-link>
        </li>
      </ul>
    </div>
  </aside>
  <div v-if="open" class="backdrop" @click="$emit('close')"></div>
</template>

<style scoped>
.sidebar {
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  width: 230px;
  flex-shrink: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 18px;
}
.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: var(--r-s);
  background: var(--brand);
  color: #05161c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 11px;
  flex-shrink: 0;
}
.brand-text {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 13.5px;
  line-height: 1.25;
}
.brand-text span {
  display: block;
  font-family: var(--font-body);
  font-weight: 400;
  font-size: 10.5px;
  color: var(--ink-muted);
}
.nav-group-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--ink-muted);
  padding: 12px 10px 6px;
}
.nav {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--r-s);
  color: var(--ink-muted);
  text-decoration: none;
  font-size: 12.8px;
  font-weight: 500;
  border-left: 2px solid transparent;
}
.nav a:hover {
  background: var(--surface-2);
  color: var(--ink);
}
.nav a.router-link-active {
  background: var(--brand-soft);
  color: var(--brand);
  border-left-color: var(--brand);
  font-weight: 600;
}
.sidebar-foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

@media (max-width: 760px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 30;
    transform: translateX(-104%);
    box-shadow: 20px 0 40px rgba(0, 0, 0, 0.35);
    transition: transform 0.2s ease;
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 25;
  }
}
</style>
