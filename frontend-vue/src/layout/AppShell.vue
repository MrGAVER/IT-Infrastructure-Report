<script setup lang="ts">
import { ref, computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import ToastHost from '../components/ToastHost.vue'
import PortSyncPlanHost from '../components/PortSyncPlanHost.vue'
import StaleRecordHost from '../components/StaleRecordHost.vue'
import { resolvePageHeading } from './pageTitles'
import { useMediaQuery } from '../composables/useMediaQuery'
import { hasOpenModal } from '../composables/modalLayer'

const sidebarOpen = ref(false)
const route = useRoute()

const heading = computed(() => resolvePageHeading(route.name, route.meta.title))

// UI-19 (ревью 2.158.0): пока на телефоне открыто выдвижное меню, всё под ним — топбар и страница — должно быть недоступно и мыши,
// и клавиатуре, и скринридеру: иначе Tab уходит за подложку, а читалка зачитывает скрытую страницу. Для этого основная область
// получает inert. На десктопе меню постоянное и фон блокировать нельзя, поэтому только при телефонной ширине (как в CSS меню).
const isPhone = useMediaQuery('(max-width: 760px)')
const backgroundInert = computed(() => sidebarOpen.value && isPhone.value)
// FE-03 (ревью ветки fix/code-review-main-f06-stage2-f05): пока открыто модальное окно, фон недоступен тоже: ловушка фокуса держит только
// Tab, а виртуальный курсор скринридера и указатель выходят за пределы окна. Окно лежит в <body> (Teleport), поэтому inert получают
// меню и основная область. Уведомления (ToastHost), PortSyncPlanHost и StaleRecordHost — соседи, а не потомки, и остаются доступными: «Сохранено» в
// момент закрытия формы должно озвучиваться. Атрибут ставит только AppShell: два источника (меню и окно) складываются через ИЛИ, и
// окно, закрывшееся под открытым меню, не снимет inert меню.
const mainInert = computed(() => backgroundInert.value || hasOpenModal.value)

// inert убирает фокус с гамбургера, поэтому после закрытия меню фокус возвращается на него (а при открытии уходит в меню — Sidebar).
watch(sidebarOpen, async (isOpen, wasOpen) => {
  if (isOpen || !wasOpen) return
  await nextTick() // inert с .main к этому моменту уже снят — иначе focus() не сработал бы
  topbar.value?.focusMenuButton()
})

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
    <Sidebar :open="sidebarOpen" :inert="hasOpenModal" @close="sidebarOpen = false" />
    <div class="main" :inert="mainInert || undefined">
      <Topbar ref="topbar" :title="heading.title" :crumb="heading.crumb" :sidebar-open="sidebarOpen" @toggle-sidebar="sidebarOpen = true" />
      <div class="content">
        <router-view />
      </div>
    </div>
    <ToastHost />
    <PortSyncPlanHost />
    <StaleRecordHost />
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
