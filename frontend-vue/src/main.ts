import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { UNAUTHORIZED_EVENT } from './api/client'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import './styles/theme.css'
import './styles/base.css'
// Стили @vue-flow/core: НЕ scoped по требованию самого пакета (см. README) — импортируются
// глобально здесь же, а не внутри DiagramView.vue, чтобы применялись одинаково независимо от
// того, какой компонент их первым использует.
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Цветовая схема хранится на сервере: сначала применяется схема по умолчанию, а когда роутер загрузит
// настройки (до первой отрисовки маршрута, см. router/index.ts) или пользователь выйдет из учётной записи,
// watch применит актуальную. Отдельной копии схемы в localStorage нет — осознанно (см. запись о переносе настроек в CHANGELOG.md).
const theme = useThemeStore(pinia)
watch(() => theme.schemeId, () => theme.applyToDocument(), { immediate: true })

// Токен истёк/отозван где-то ещё (logout на другой вкладке, смена пароля администратором,
// TTL сессии) — client.ts не импортирует стор напрямую (см. комментарий там про циклы
// импорта), поэтому подписка на глобальное событие живёт здесь, в точке входа.
const authStore = useAuthStore(pinia)
window.addEventListener(UNAUTHORIZED_EVENT, () => authStore.handleUnauthorized())

app.mount('#app')
