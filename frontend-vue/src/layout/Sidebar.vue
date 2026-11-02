<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useOrganizationStore } from '../stores/organization'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const organization = useOrganizationStore()
const auth = useAuthStore()
const router = useRouter()
// Журнал аудита виден только тому, кому его отдаёт сервер (A-23): viewer получил бы 403.
const visibleSystemNav = computed(() => systemNav.filter((item) => !item.adminOnly || auth.canViewAuditLog))

// UI-10 (ревью merge/review-2158-executors): мобильное меню закрывается по Esc. Слушатель на document, а не на
// самом меню: фокус после открытия остаётся на кнопке-гамбургере в топбаре, то есть вне <aside>.
function onKeydown(event: KeyboardEvent) {
  if (!props.open || event.key !== 'Escape' || event.defaultPrevented) return
  // Забираем Esc себе (UI-04): иначе он дойдёт до useEscapeClose и закроет ещё и окно, если оно оказалось открытым.
  event.preventDefault()
  emit('close')
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

async function logout() {
  await auth.logout()
  emit('close')
  router.replace({ name: 'login' })
}

// Каждому пункту — своя иконка (UI-11): раньше i-layers стояла у четырёх пунктов, i-box, i-sitemap и i-network — у двух.
// Тест «у каждого пункта меню своя иконка» в Sidebar.spec.ts не даст повторить это снова.
const primaryNav = [
  { to: '/dashboard', icon: 'i-home', label: 'Дашборд' },
  { to: '/information-systems', icon: 'i-database', label: 'Информационные системы' },
  { to: '/devices', icon: 'i-server', label: 'Инвентаризация устройств' },
  { to: '/device-stacks', icon: 'i-layers', label: 'Стеки устройств' },
  { to: '/connections', icon: 'i-network', label: 'Подключения' },
  { to: '/diagrams', icon: 'i-sitemap', label: 'Диаграмма топологии сети' },
  { to: '/vms', icon: 'i-cpu', label: 'Виртуальные машины' },
  { to: '/containers', icon: 'i-box', label: 'Контейнеры' },
]
const catalogNav = [
  { to: '/vlans', icon: 'i-grid', label: 'VLAN' },
  { to: '/buildings', icon: 'i-building', label: 'Здания и помещения' },
  { to: '/structural-units', icon: 'i-users', label: 'Структурные подразделения' },
  { to: '/other-catalogs', icon: 'i-book', label: 'Другие справочники' },
]
const systemNav = [
  { to: '/reports', icon: 'i-file', label: 'Отчёты' },
  { to: '/report-templates', icon: 'i-template', label: 'Шаблоны отчётов' },
  { to: '/port-sync-rules', icon: 'i-shuffle', label: 'Правила согласования портов' },
  { to: '/audit-log', icon: 'i-activity', label: 'Журнал аудита', adminOnly: true },
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
      <li v-for="item in visibleSystemNav" :key="item.to">
        <router-link :to="item.to" @click="$emit('close')">
          <svg class="icon"><use :href="`/icons.svg#${item.icon}`" /></svg>
          {{ item.label }}
        </router-link>
      </li>
    </ul>

    <div class="sidebar-foot">
      <div v-if="auth.enabled && auth.user" class="user-badge">
        <svg class="icon"><use href="/icons.svg#i-user" /></svg>
        <span class="user-name">{{ auth.user.username }}</span>
        <span class="user-role">{{ auth.isAdmin ? 'администратор' : 'просмотр' }}</span>
      </div>
      <ul class="nav">
        <li>
          <router-link to="/settings" @click="$emit('close')">
            <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
            Настройки
          </router-link>
        </li>
        <li v-if="auth.enabled && auth.user">
          <button type="button" class="nav-button" @click="logout">
            <svg class="icon"><use href="/icons.svg#i-log-out" /></svg>
            Выйти
          </button>
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
.user-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px 10px;
  font-size: 12px;
}
.user-badge .icon {
  color: var(--ink-muted);
}
.user-name {
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  margin-left: auto;
  font-size: 10px;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.nav-button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--r-s);
  color: var(--ink-muted);
  background: none;
  border: none;
  border-left: 2px solid transparent;
  font-size: 12.8px;
  font-weight: 500;
  font-family: inherit;
  text-align: left;
}
.nav-button:hover {
  background: var(--surface-2);
  color: var(--ink);
}

/* UI-5: на десктопе сайдбар остаётся на месте, пока прокручивается страница, — «Настройки» и «Выйти» не уезжают
   в самый низ длинного документа. Своя прокрутка нужна, когда пунктов больше, чем влезает в окно. */
@media (min-width: 761px) {
  .sidebar {
    position: sticky;
    top: 0;
    align-self: flex-start;
    height: 100vh;
    height: 100dvh;
    overflow-x: hidden;
    overflow-y: auto;
  }
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
    /* UI-1: у position: fixed нет собственной прокрутки страницы — на 390×667 содержимое (823 px) обрезалось, и пункты
       от «Шаблонов отчётов» до «Выйти» были недоступны. */
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-bottom: calc(16px + env(safe-area-inset-bottom));
  }
  .sidebar.open {
    transform: translateX(0);
  }
  /* UI-10: закрытое меню лишь сдвинуто за экран, но остаётся в порядке фокуса (первый Tab попадал на скрытую ссылку).
     visibility включается с задержкой на время анимации закрытия, при открытии — сразу (у .open своя transition). */
  .sidebar:not(.open) {
    visibility: hidden;
    transition:
      transform 0.2s ease,
      visibility 0s 0.2s;
  }
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 25;
  }
}
</style>
