import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
  },
  {
    path: '/information-systems',
    name: 'information-systems',
    component: () => import('../views/InformationSystemsView.vue'),
  },
  {
    path: '/devices',
    name: 'devices',
    component: () => import('../views/DevicesView.vue'),
  },
  {
    path: '/connections',
    name: 'connections',
    component: () => import('../views/ConnectionsView.vue'),
  },
  {
    path: '/vms',
    name: 'vms',
    component: () => import('../views/VMsView.vue'),
  },
  {
    path: '/vlans',
    name: 'vlans',
    component: () => import('../views/PlaceholderView.vue'),
    props: { title: 'VLAN' },
  },
  {
    path: '/buildings',
    name: 'buildings',
    component: () => import('../views/PlaceholderView.vue'),
    props: { title: 'Здания и помещения' },
  },
  {
    path: '/structural-units',
    name: 'structural-units',
    component: () => import('../views/PlaceholderView.vue'),
    props: { title: 'Структурные подразделения' },
  },
  {
    path: '/reports',
    name: 'reports',
    component: () => import('../views/ReportsView.vue'),
  },
  {
    path: '/audit-log',
    name: 'audit-log',
    component: () => import('../views/PlaceholderView.vue'),
    props: { title: 'Журнал аудита' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../views/SettingsView.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
