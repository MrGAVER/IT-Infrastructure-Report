import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
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
    path: '/containers',
    name: 'containers',
    component: () => import('../views/ContainersView.vue'),
  },
  {
    path: '/vlans',
    name: 'vlans',
    component: () => import('../views/VLANsView.vue'),
  },
  {
    path: '/buildings',
    name: 'buildings',
    component: () => import('../views/BuildingsView.vue'),
  },
  {
    path: '/structural-units',
    name: 'structural-units',
    component: () => import('../views/StructuralUnitsView.vue'),
  },
  {
    path: '/other-catalogs',
    name: 'other-catalogs',
    component: () => import('../views/OtherCatalogsView.vue'),
  },
  {
    path: '/reports',
    name: 'reports',
    component: () => import('../views/ReportsView.vue'),
  },
  {
    path: '/report-templates',
    name: 'report-templates',
    component: () => import('../views/ReportTemplatesView.vue'),
  },
  {
    path: '/report-templates/:id/editor',
    name: 'report-template-editor',
    component: () => import('../views/ReportGridEditorView.vue'),
  },
  {
    path: '/report-templates/:id/editor-docx',
    name: 'report-template-editor-docx',
    component: () => import('../views/ReportDocxEditorView.vue'),
  },
  {
    path: '/audit-log',
    name: 'audit-log',
    component: () => import('../views/AuditLogView.vue'),
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

// Единая точка контроля доступа на клиенте — не замена серверной проверке (middleware в
// backend/app/services/auth.py по-прежнему решает, что реально можно прочитать/изменить), а
// UX-уровень: не показывать защищённые экраны, если сессии нет, и не показывать форму входа
// тому, кто уже вошёл (или если тумблер вообще выключен — однопользовательский режим).
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) await auth.init()

  if (auth.needsLogin) {
    if (to.name === 'login') return true
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login') {
    const redirect = typeof to.query.redirect === 'string' ? to.query.redirect : '/dashboard'
    return redirect
  }
  return true
})
