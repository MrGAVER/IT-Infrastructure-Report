<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { useAuthStore } from '../stores/auth'

// sidebarOpen — состояние мобильного меню: гамбургер сообщает его через aria-expanded (UI-19).
defineProps<{ title: string; crumb: string; sidebarOpen?: boolean }>()
defineEmits<{ 'toggle-sidebar': [] }>()

// Фокус возвращается на гамбургер после закрытия меню (AppShell): пока меню открыто, топбар inert, и фокус с него уходит.
const burgerEl = ref<HTMLButtonElement | null>(null)
defineExpose({ focusMenuButton: () => burgerEl.value?.focus() })

const auth = useAuthStore()
const router = useRouter()

// Фикс auth п.1.2 (батч4): реальные имя/роль/кружок-инициал вместо статичного текста
// "Администратор" — раньше topbar не был подключён к authStore вообще (см. Sidebar.vue, у
// которого уже есть похожий, но более простой бейдж без выпадающего меню). Тот же приём
// "клик вне области закрывает" уже используется в SearchableSelect.vue.
const menuOpen = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLButtonElement | null>(null)

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function onDocumentClick(event: MouseEvent) {
  if (menuOpen.value && rootEl.value && !rootEl.value.contains(event.target as Node)) menuOpen.value = false
}

// UI-10 (ревью merge/review-2158-executors): Esc закрывает меню и возвращает фокус на кнопку-чип, откуда его открыли, —
// иначе клавиатурный пользователь терял место в порядке обхода.
function onDocumentKeydown(event: KeyboardEvent) {
  if (!menuOpen.value || event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault() // забираем Esc себе (UI-04): окно под меню не должно закрыться тем же нажатием
  menuOpen.value = false
  triggerEl.value?.focus()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})

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
    <button
      ref="burgerEl"
      type="button"
      class="hamburger"
      aria-label="Меню"
      aria-controls="app-sidebar"
      :aria-expanded="sidebarOpen === true"
      @click="$emit('toggle-sidebar')"
    >
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
        <button ref="triggerEl" type="button" class="user-chip-trigger" :aria-expanded="menuOpen" aria-haspopup="menu" @click="toggleMenu">
          <!-- UI-19: внутри <button> допустимо только фразовое содержимое — <span>, не <div> (display задаётся стилями). -->
          <span class="avatar">{{ auth.user.username.charAt(0).toUpperCase() }}</span>
          <span class="who">
            <b>{{ auth.user.username }}</b>
            <span>{{ auth.isAdmin ? 'Администратор' : 'Только просмотр' }}</span>
          </span>
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
  /* UI-5: топбар остаётся вверху окна, пока прокручивается длинная страница (и гамбургер доступен на телефоне).
     Слой --z-raised ниже подложки мобильного меню, самого меню и модальных окон (шкала — в styles/theme.css). */
  position: sticky;
  top: 0;
  z-index: var(--z-raised);
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
/* Без min-width: 0 длинный заголовок распирал бы флекс-контейнер, а не сжимался и не переносился. */
.titles {
  min-width: 0;
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
/* UI-7: --surface-1 — алиас на --surface (theme.css), то есть ровно фон топбара и меню: hover был невидим. */
.user-chip-trigger:hover {
  background: var(--surface-2);
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
  display: block;
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
  box-shadow: var(--shadow-m);
  padding: 6px;
  z-index: var(--z-menu);
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
  background: var(--surface-2);
}

@media (max-width: 760px) {
  /* UI-05: на 390 px шапка с заголовком «Инвентаризация физических устройств» занимала ≈ 125 из 844 px. Хлебные крошки на
     телефоне не нужны (раздел виден в меню), заголовок — не больше двух строк, отступы короче. */
  .topbar {
    gap: 10px;
    padding: 10px 14px;
  }
  .topbar-right {
    gap: 10px;
  }
  .crumb {
    display: none;
  }
  .page-title {
    font-size: 16px;
    line-height: 1.25;
    margin-top: 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .hamburger {
    display: block;
  }
  .who {
    display: none;
  }
}
</style>
