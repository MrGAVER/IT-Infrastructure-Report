<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { useAuthStore } from '../stores/auth'

defineProps<{ title: string; crumb: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()

const auth = useAuthStore()
const router = useRouter()

// Фикс auth п.1.2 (батч4): реальные имя/роль/кружок-инициал вместо статичного текста
// "Администратор" — раньше topbar не был подключён к authStore вообще (см. Sidebar.vue, у
// которого уже есть похожий, но более простой бейдж без выпадающего меню). Тот же приём
// "клик вне области закрывает" уже используется в SearchableSelect.vue.
const menuOpen = ref(false)
const rootEl = ref<HTMLElement | null>(null)

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function onDocumentClick(event: MouseEvent) {
  if (menuOpen.value && rootEl.value && !rootEl.value.contains(event.target as Node)) menuOpen.value = false
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

// Фикс auth п.1.1 (батч4): выход из топбара — тот же переход на /login, что уже делает
// Sidebar.vue:logout(), продублирован здесь намеренно (два независимых места входа в один и тот
// же выход, не стоит городить общий composable ради трёх строк).
async function logout() {
  menuOpen.value = false
  await auth.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <div class="topbar">
    <button class="hamburger" aria-label="Меню" @click="$emit('toggle-sidebar')">
      <svg class="icon"><use href="/icons.svg#i-menu" /></svg>
    </button>
    <div class="titles">
      <div class="crumb">{{ crumb }}</div>
      <div class="page-title">{{ title }}</div>
    </div>
    <div class="topbar-right">
      <slot name="right" />
      <ThemeSwitcher compact />
      <div v-if="auth.enabled && auth.user" ref="rootEl" class="user-chip">
        <button type="button" class="user-chip-trigger" :aria-expanded="menuOpen" aria-haspopup="menu" @click="toggleMenu">
          <div class="avatar">{{ auth.user.username.charAt(0).toUpperCase() }}</div>
          <div class="who">
            <b>{{ auth.user.username }}</b>
            <span>{{ auth.isAdmin ? 'Администратор' : 'Только просмотр' }}</span>
          </div>
          <svg class="icon chevron" :class="{ open: menuOpen }"><use href="/icons.svg#i-chevd" /></svg>
        </button>
        <div v-if="menuOpen" class="user-menu" role="menu">
          <button type="button" class="user-menu-item" role="menuitem" @click="logout">
            <svg class="icon"><use href="/icons.svg#i-log-out" /></svg>
            Выйти
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.hamburger {
  display: none;
  background: none;
  border: none;
  color: var(--ink);
  padding: 4px;
}
.hamburger .icon {
  width: 20px;
  height: 20px;
}
.crumb {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.page-title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 19px;
  margin-top: 2px;
}
.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 16px;
}
.user-chip {
  position: relative;
  padding-left: 12px;
  border-left: 1px solid var(--border);
}
.user-chip-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: none;
  padding: 4px;
  border-radius: var(--r-s);
  cursor: pointer;
  color: var(--ink);
}
.user-chip-trigger:hover {
  background: var(--surface-1, rgba(127, 127, 127, 0.08));
}
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--brand);
  color: #05161c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
  flex-shrink: 0;
}
.who {
  font-size: 11.5px;
  line-height: 1.3;
  text-align: left;
}
.who b {
  display: block;
  font-size: 12px;
  font-weight: 700;
}
.who span {
  color: var(--ink-muted);
}
.chevron {
  width: 14px;
  height: 14px;
  color: var(--ink-muted);
  transition: transform 0.15s ease;
}
.chevron.open {
  transform: rotate(180deg);
}
.user-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 160px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  box-shadow: var(--shadow-m, 0 8px 24px rgba(0, 0, 0, 0.16));
  padding: 6px;
  z-index: 30;
}
.user-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  padding: 8px 10px;
  border-radius: var(--r-s);
  font-size: 12.5px;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}
.user-menu-item:hover {
  background: var(--surface-1, rgba(127, 127, 127, 0.08));
}

@media (max-width: 760px) {
  .hamburger {
    display: block;
  }
  .who {
    display: none;
  }
}
</style>
