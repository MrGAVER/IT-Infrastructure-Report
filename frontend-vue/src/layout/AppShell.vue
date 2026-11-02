<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import ToastHost from '../components/ToastHost.vue'
import PortSyncPlanHost from '../components/PortSyncPlanHost.vue'
import { resolvePageHeading } from './pageTitles'

const sidebarOpen = ref(false)
const route = useRoute()

const heading = computed(() => resolvePageHeading(route.name, route.meta.title))

// UI-05 (ревью 2.158.0): экраны на всю высоту окна (диаграмма) раньше вычитали из 100vh «магические» 96 px, не зная реальной
// высоты липкой шапки, — на телефоне, где заголовок переносится, документ получал лишнюю прокрутку. Теперь фактическая высота
// шапки публикуется в --topbar-h на корне оболочки и следует за ней при любом переносе и смене ширины окна.
const shellEl = ref<HTMLElement | null>(null)
const topbar = ref<InstanceType<typeof Topbar> | null>(null)
let topbarObserver: ResizeObserver | null = null

function publishTopbarHeight() {
  const el = topbar.value?.$el as HTMLElement | undefined
  if (!el || !shellEl.value) return
  // Округление вверх: дробная высота шапки иначе оставляла бы экран на высоту окна короче на долю пикселя ниже нуля.
  shellEl.value.style.setProperty('--topbar-h', `${Math.ceil(el.getBoundingClientRect().height)}px`)
}

onMounted(() => {
  publishTopbarHeight()
  const el = topbar.value?.$el as HTMLElement | undefined
  if (el && typeof ResizeObserver !== 'undefined') {
    topbarObserver = new ResizeObserver(publishTopbarHeight)
    topbarObserver.observe(el)
  }
})
onBeforeUnmount(() => topbarObserver?.disconnect())
</script>

<template>
  <div ref="shellEl" class="app-shell">
    <Sidebar :open="sidebarOpen" @close="sidebarOpen = false" />
    <div class="main">
      <Topbar ref="topbar" :title="heading.title" :crumb="heading.crumb" @toggle-sidebar="sidebarOpen = true" />
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
  /* Отступы области контента — переменными: экран на всю высоту окна (DiagramView) вычитает их вместе с --topbar-h. */
  --content-pad-top: 18px;
  --content-pad-bottom: 32px;
  display: flex;
  min-height: 100vh;
  min-height: 100dvh;
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.content {
  padding: var(--content-pad-top) 20px var(--content-pad-bottom);
  overflow: auto;
}
</style>
