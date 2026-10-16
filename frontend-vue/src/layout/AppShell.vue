<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import ToastHost from '../components/ToastHost.vue'
import PortSyncPlanHost from '../components/PortSyncPlanHost.vue'
import { resolvePageHeading } from './pageTitles'

const sidebarOpen = ref(false)
const route = useRoute()

const heading = computed(() => resolvePageHeading(route.name, route.meta.title))
</script>

<template>
  <div class="app-shell">
    <Sidebar :open="sidebarOpen" @close="sidebarOpen = false" />
    <div class="main">
      <Topbar :title="heading.title" :crumb="heading.crumb" @toggle-sidebar="sidebarOpen = true" />
      <div class="content">
        <router-view />
      </div>
    </div>
    <ToastHost />
    <PortSyncPlanHost />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.content {
  padding: 18px 20px 32px;
  overflow: auto;
}
</style>
