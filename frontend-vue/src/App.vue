<script setup lang="ts">
import { useRoute } from 'vue-router'
import AppShell from './layout/AppShell.vue'

// Экран входа — единственный маршрут вне AppShell (без сайдбара/топбара): показывать
// навигацию по разделам реестра тому, кто ещё не вошёл, нет смысла, а верстать его как ещё
// один "слот" внутри чужого layout'а только ради общей рамки — сложнее, чем отдельная ветка тут.
// LoginView.vue рендерится через <router-view> (не статическим импортом сюда) — так у него
// остаётся один-единственный, ленивый, путь загрузки через router/index.ts.
const route = useRoute()
</script>

<template>
  <router-view v-if="route.name === 'login'" />
  <AppShell v-else />
</template>
