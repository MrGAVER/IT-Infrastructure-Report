import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { UNAUTHORIZED_EVENT } from './api/client'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import './styles/theme.css'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Применяем сохранённую цветовую схему до первой отрисовки, чтобы избежать
// вспышки схемы по умолчанию (FOUC) при повторном визите.
useThemeStore(pinia).applyToDocument()

// Токен истёк/отозван где-то ещё (logout на другой вкладке, смена пароля администратором,
// TTL сессии) — client.ts не импортирует стор напрямую (см. комментарий там про циклы
// импорта), поэтому подписка на глобальное событие живёт здесь, в точке входа.
const authStore = useAuthStore(pinia)
window.addEventListener(UNAUTHORIZED_EVENT, () => authStore.handleUnauthorized())

app.mount('#app')
