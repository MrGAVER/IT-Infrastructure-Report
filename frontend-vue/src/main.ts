import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
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

app.mount('#app')
