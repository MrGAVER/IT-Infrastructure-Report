<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from './layout/AppShell.vue'
import { useAuthStore } from './stores/auth'

// Экран входа — единственный маршрут вне AppShell (без сайдбара/топбара): показывать
// навигацию по разделам реестра тому, кто ещё не вошёл, нет смысла, а верстать его как ещё
// один "слот" внутри чужого layout'а только ради общей рамки — сложнее, чем отдельная ветка тут.
// LoginView.vue рендерится через <router-view> (не статическим импортом сюда) — так у него
// остаётся один-единственный, ленивый, путь загрузки через router/index.ts.
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// Фикс auth п.1.1 (батч4): роутер-гард (router/index.ts) решает, пускать ли на защищённый
// маршрут, только В МОМЕНТ навигации — если пользователь просто сидит на открытой странице,
// а auth.needsLogin становится true "из-под него" (администратор включил аутентификацию —
// см. stores/auth.ts:setEnabled, или токен истёк/отозван на сервере — см. handleUnauthorized
// в main.ts), гард не сработает сам по себе, пока пользователь куда-нибудь не перейдёт. Этот
// watch — единственное место, которое реагирует на сам ФАКТ смены needsLogin, а не на попытку
// навигации, и форсирует переход на /login сразу, а не после следующего клика.
watch(
  () => auth.needsLogin,
  (needsLogin) => {
    if (needsLogin && route.name !== 'login') {
      router.replace({ name: 'login', query: { redirect: route.fullPath } })
    }
  },
)
</script>

<template>
  <router-view v-if="route.name === 'login'" />
  <AppShell v-else />
</template>
