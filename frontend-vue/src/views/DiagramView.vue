<script setup lang="ts">
// Экран одной диаграммы топологии сети (раздел 11 ТЗ). @vue-flow/core — основная зависимость холста (раздел 11 ТЗ);
// панорамирование и масштабирование колесом встроены в неё. Кнопки масштаба — собственный компонент
// (DiagramZoomControls.vue), мини-карта — пакет @vue-flow/minimap (UI-02, ревью 2.158.0): без них диаграмму на 30+ узлов не
// охватить, а на телефоне нечем увеличить. Декоративный @vue-flow/background по-прежнему не подключён.
//
// localNodes/localEdges — v-model, привязанный к @vue-flow/core (это их задокументированный
// способ "управляемого" состояния канваса, см. README примеров пакета): библиотеке нужен
// СОБСТВЕННЫЙ реактивный массив, который она мутирует при драге/зуме, иначе перетаскивание узла
// не будет визуально плавным. Источник истины при этом остаётся стор (useDiagramStore) —
// localNodes/localEdges пересобираются из него заново при каждой загрузке/пересборке диаграммы
// (см. syncFromStore), а обратно в стор данные идут ТОЛЬКО через явные действия
// (onNodeDragStop -> store.moveNode, раздел 4.6 ТЗ), а не автоматической синхронизацией.
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, type Edge, type EdgeMouseEvent, type GraphNode, type Node, type NodeDragEvent, type NodeMouseEvent } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/minimap/dist/style.css'
import { useDiagramStore } from '../stores/diagram'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import DiagramDeviceNode from '../components/diagram/DiagramDeviceNode.vue'
import DiagramGroupNode from '../components/diagram/DiagramGroupNode.vue'
import DiagramConnectionEdge from '../components/diagram/DiagramConnectionEdge.vue'
import DiagramDetailPanel from '../components/diagram/DiagramDetailPanel.vue'
import DiagramExportPanel from '../components/diagram/DiagramExportPanel.vue'
import DiagramZoomControls from '../components/diagram/DiagramZoomControls.vue'
import { useMediaQuery } from '../composables/useMediaQuery'
import { CONNECTION_EDGE_TYPE, edgeBaseStyle, edgeIsRelatedToHover, GROUP_PREFIX, groupKeyOf, toFlowEdge, toFlowNode } from '../utils/diagramFlow'
import { FIT_VIEW_OPTIONS, resolveInitialView } from '../utils/diagramViewport'
import { EDGE_LABEL_LAYOUT_KEY, computeEdgeLabelLayout, edgeLabelsVisible } from '../utils/diagramEdgeLabels'
import { EDGE_ROUTES_KEY, routeEdges, routeInputsFromFlow, type EdgeRouteMap } from '../utils/diagramEdgeRouting'
import type { DiagramEdge, DiagramExportFormat, DiagramNode } from '../api/diagrams'

const route = useRoute()
const router = useRouter()
const store = useDiagramStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()
const { fitView, setViewport, onNodesInitialized, viewport, getNodes } = useVueFlow()

const diagramId = computed(() => String(route.params.id))

// UI-22 (ревью 2.158.0): слоты подписей портов и группы параллельных связей считаются один раз на диаграмму и отдаются рёбрам через
// provide — данные рёбер (контракт API) остаются нетронутыми. На мелком масштабе (< 0,6) подписи рёбер скрыты классом на холсте.
provide(
  EDGE_LABEL_LAYOUT_KEY,
  computed(() => computeEdgeLabelLayout(store.diagram?.edges ?? [])),
)
const labelsHidden = computed(() => !edgeLabelsVisible(viewport.value.zoom))

// F-07: ортогональные маршруты рёбер в обход узлов. Считаются сразу для всех рёбер, потому что маршрут одного зависит от остальных
// (занятые дорожки) и от всех узлов (препятствия), и отдаются рёбрам через provide. Пересчёт — когда узлы измерены (первая отрисовка,
// «Пересобрать», разворачивание группы) и после остановки перетаскивания; пока узел тащат, маршруты его рёбер не совпадают с хэндлами,
// и DiagramConnectionEdge рисует их прежней кривой. Небольшая задержка собирает серию событий в один расчёт.
const ROUTE_RECALC_DELAY_MS = 60
const edgeRoutes = shallowRef<EdgeRouteMap>(new Map())
provide(EDGE_ROUTES_KEY, edgeRoutes)
let routeTimer: ReturnType<typeof setTimeout> | undefined
function recomputeRoutes() {
  routeTimer = undefined
  const { nodes, requests } = routeInputsFromFlow(getNodes.value, localEdges.value)
  edgeRoutes.value = routeEdges(nodes, requests)
}
function scheduleRouteRecalc() {
  if (routeTimer !== undefined) clearTimeout(routeTimer)
  routeTimer = setTimeout(recomputeRoutes, ROUTE_RECALC_DELAY_MS)
}

// Мини-карта на телефоне занимает заметную часть холста шириной 350 px, а ориентироваться там помогают кнопки масштаба.
const isPhone = useMediaQuery('(max-width: 760px)')
const MINIMAP_NEUTRAL_COLOR = '#8fa0b3'
function miniMapNodeColor(node: GraphNode): string {
  const data = node.data as DiagramNode | undefined
  return data?.type === 'device' && 'color' in data.icon && data.icon.color ? data.icon.color : MINIMAP_NEUTRAL_COLOR
}

const localNodes = ref<Node<DiagramNode>[]>([])
const localEdges = ref<Edge<DiagramEdge>[]>([])

function syncFromStore() {
  // Аннотация здесь не обычная стилистическая придирка: `vue-tsc -b` (в отличие от `--noEmit`)
  // проваливался с TS2589 "Type instantiation is excessively deep" при попытке вывести тип
  // напрямую из геттера Pinia-стора внутри .map() — разрыв цепочки вывода через промежуточную
  // явно типизированную переменную устраняет проблему без потери типобезопасности.
  const nodes: DiagramNode[] = store.nodes
  const edges: DiagramEdge[] = store.edges
  localNodes.value = nodes.map((n) => toFlowNode(n)) as Node<DiagramNode>[]
  localEdges.value = edges.map((e) => toFlowEdge(e)) as Edge<DiagramEdge>[]
}

// UI-01 (ревью 2.158.0): раньше fitView() вызывался в requestAnimationFrame сразу после установки узлов — до того, как Vue Flow
// измерил их размеры, — и граф оставался в масштабе 1 со сдвигом 0, обрезанный по краю холста. Теперь начальный вид применяется
// по событию nodesInitialized (у всех узлов уже есть размеры). Флаг нужен, чтобы событие, которое приходит и при каждой
// следующей замене узлов (разворачивание группы, «Пересобрать»), не сбрасывало вид, выбранный пользователем.
let applyInitialView = false

async function loadDiagram() {
  await store.load(diagramId.value)
  if (store.diagram) applyInitialView = true
  syncFromStore()
}

onNodesInitialized(() => {
  scheduleRouteRecalc()
  if (!applyInitialView) return
  applyInitialView = false
  const view = resolveInitialView(store.diagram?.viewport)
  if (view.kind === 'restore') void setViewport(view.viewport)
  else void fitView(FIT_VIEW_OPTIONS)
})

onMounted(loadDiagram)
watch(diagramId, loadDiagram)
// Сдвиг узла уходит на сервер с задержкой (debounce в сторе): при уходе с экрана отправляем его сразу.
// Смену диаграммы на этом же экране покрывает store.load(). Ошибка сохранения остаётся в store.error.
onBeforeUnmount(() => {
  if (routeTimer !== undefined) clearTimeout(routeTimer)
  void store.flushLayoutSave()
})

/** Раздел 13 ТЗ (план фронтенда): "клик по свёрнутой группе → локальное обновление без полной
 * перезагрузки" — под "полной перезагрузкой" имеется в виду перезагрузка СТРАНИЦЫ/навигация, а
 * не сетевой запрос вообще: store.toggleGroup() всё равно обращается к бэкенду (сохранить
 * is_collapsed и пересобрать граф с учётом новых узлов), но без роутинга/переинициализации
 * компонента — только syncFromStore() поверх уже открытого канваса. */
async function expandGroup(nodeId: string) {
  try {
    await store.toggleGroup(groupKeyOf(nodeId), false)
    syncFromStore()
  } catch (e) {
    notifyError(e)
  }
}

function onNodeClick({ node }: NodeMouseEvent) {
  const data = node.data as DiagramNode
  if (data.type === 'group' && auth.canWrite) {
    void expandGroup(data.id)
    return
  }
  store.selectNode(data)
}
function onEdgeClick({ edge }: EdgeMouseEvent) {
  store.selectEdge(edge.data as DiagramEdge)
}
function onPaneClick() {
  store.clearSelection()
}
function onNodeDragStop({ node }: NodeDragEvent) {
  scheduleRouteRecalc()
  store.moveNode(node.id, node.position.x, node.position.y)
}

// Пункт 4 правки "диаграмма топологии сети": при большом числе связей трудно понять, что куда
// идёт. Наведение на узел или ребро подсвечивает связанные с ним линии и приглушает остальные
// (см. edgeIsRelatedToHover в utils/diagramFlow.ts) — сами линии/их геометрия не меняются,
// только подсказка взгляду. Патчим style существующих элементов localEdges.value НА МЕСТЕ (а не
// пересобираем localEdges целиком, как это делает syncFromStore) — иначе на каждое движение
// мыши терялось бы состояние драга/позиций, которое @vue-flow/core держит в этом же массиве.
const hoveredNodeId = ref<string | null>(null)
const hoveredEdgeId = ref<string | null>(null)

function onNodeMouseEnter({ node }: NodeMouseEvent) {
  hoveredNodeId.value = node.id
}
function onNodeMouseLeave() {
  hoveredNodeId.value = null
}
function onEdgeMouseEnter({ edge }: EdgeMouseEvent) {
  hoveredEdgeId.value = edge.id
}
function onEdgeMouseLeave() {
  hoveredEdgeId.value = null
}

watch([hoveredNodeId, hoveredEdgeId], () => {
  const hovering = hoveredNodeId.value !== null || hoveredEdgeId.value !== null
  for (const e of localEdges.value) {
    const edgeData = e.data as DiagramEdge
    const base = edgeBaseStyle(edgeData)
    if (!hovering) {
      e.style = base
      continue
    }
    const related = edgeIsRelatedToHover(edgeData, hoveredNodeId.value, hoveredEdgeId.value)
    e.style = { ...base, opacity: related ? 1 : 0.15 }
  }
})

async function onExport(format: DiagramExportFormat) {
  try {
    await store.exportAs(format)
    notify(`Файл .${format} скачан`, 'success')
  } catch (e) {
    notifyError(e)
  }
}

async function onRegenerate() {
  try {
    await store.regenerate()
    syncFromStore()
    notify('Диаграмма пересобрана', 'success')
  } catch (e) {
    notifyError(e)
  }
}

async function onDuplicate() {
  try {
    const dup = await store.duplicate()
    if (dup) {
      notify('Диаграмма продублирована', 'success')
      router.push({ name: 'diagram-detail', params: { id: dup.id } })
    }
  } catch (e) {
    notifyError(e)
  }
}

async function onDelete() {
  if (!store.diagram) return
  if (!confirm(`Удалить диаграмму «${store.diagram.name}»?`)) return
  try {
    await store.remove()
    notify('Диаграмма удалена', 'success')
    router.push({ name: 'diagrams' })
  } catch (e) {
    notifyError(e)
  }
}

// Пункт 8 правки "диаграмма топологии сети": переименование прямо в заголовке — щелчок по
// карандашу превращает подпись в поле ввода; Enter/потеря фокуса сохраняют, Esc отменяет.
// Ошибка (напр. "такое имя уже занято") показывается тут же под полем, а не тостом — режим
// редактирования при этом остаётся открытым для повторной попытки, а не закрывается вслепую.
const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)

function startRename() {
  if (!store.diagram) return
  renameValue.value = store.diagram.name
  renameError.value = null
  renaming.value = true
  nextTick(() => renameInput.value?.focus())
}

function cancelRename() {
  if (!store.diagram) return
  // Возвращаем черновик к текущему имени — иначе следующий blur (фокус уходит из поля сразу
  // после Esc) попытался бы всё равно сохранить то, что пользователь как раз хотел отменить.
  renameValue.value = store.diagram.name
  renameError.value = null
  renaming.value = false
}

async function commitRename() {
  if (!store.diagram) return
  const name = renameValue.value.trim()
  if (name === store.diagram.name) {
    renaming.value = false
    renameError.value = null
    return
  }
  if (!name) {
    renameError.value = 'Укажите название'
    return
  }
  try {
    await store.rename(name)
    renaming.value = false
    renameError.value = null
  } catch (e) {
    renameError.value = e instanceof Error ? e.message : 'Не удалось переименовать диаграмму'
  }
}
</script>

<template>
  <div class="diagram-view">
    <div class="toolbar">
      <button class="btn btn-secondary" type="button" @click="router.push({ name: 'diagrams' })">
        <svg class="icon"><use href="/icons.svg#i-arrow-left" /></svg>
        К списку
      </button>
      <div v-if="!renaming" class="diagram-name-wrap">
        <span class="diagram-name">{{ store.diagram?.name }}</span>
        <button v-if="auth.canWrite" type="button" class="icon-btn" aria-label="Переименовать диаграмму" @click="startRename">
          <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
        </button>
      </div>
      <div v-else class="rename-wrap">
        <input
          ref="renameInput"
          v-model="renameValue"
          type="text"
          maxlength="255"
          class="rename-input"
          @keydown.enter="commitRename"
          @keydown.esc="cancelRename"
          @blur="commitRename"
        />
        <span v-if="renameError" class="rename-error">{{ renameError }}</span>
      </div>
      <span v-if="store.savingLayout" class="saving-hint">сохранение раскладки…</span>
      <div class="spacer"></div>
      <button v-if="auth.canWrite" class="btn btn-secondary" type="button" :disabled="store.loading" @click="onRegenerate">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Пересобрать
      </button>
      <button v-if="auth.canWrite" class="btn btn-secondary" type="button" @click="onDuplicate">Дублировать</button>
      <button v-if="auth.canWrite" class="btn btn-secondary" type="button" @click="onDelete">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        Удалить
      </button>
      <DiagramExportPanel :exporting="store.exporting" :last-format="store.diagram?.last_export_format ?? null" @export="onExport" />
    </div>

    <div v-if="store.error" class="error-banner card">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
      {{ store.error }}
    </div>
    <div v-else-if="store.loading && !store.diagram" class="loading-banner">Загрузка диаграммы…</div>

    <div v-else class="canvas-wrap" :class="{ 'labels-hidden': labelsHidden }">
      <VueFlow
        v-model:nodes="localNodes"
        v-model:edges="localEdges"
        :min-zoom="0.1"
        :max-zoom="2.5"
        :nodes-connectable="false"
        :nodes-draggable="auth.canWrite"
        @node-click="onNodeClick"
        @edge-click="onEdgeClick"
        @pane-click="onPaneClick"
        @node-drag-stop="onNodeDragStop"
        @node-mouse-enter="onNodeMouseEnter"
        @node-mouse-leave="onNodeMouseLeave"
        @edge-mouse-enter="onEdgeMouseEnter"
        @edge-mouse-leave="onEdgeMouseLeave"
      >
        <template #node-device="nodeProps"><DiagramDeviceNode v-bind="nodeProps" /></template>
        <template #node-group="nodeProps"><DiagramGroupNode v-bind="nodeProps" /></template>
        <template #[`edge-${CONNECTION_EDGE_TYPE}`]="edgeProps"><DiagramConnectionEdge v-bind="edgeProps" /></template>
        <DiagramZoomControls />
        <MiniMap
          v-if="!isPhone"
          class="diagram-minimap"
          position="bottom-left"
          pannable
          zoomable
          aria-label="Мини-карта диаграммы"
          :node-color="miniMapNodeColor"
          :width="160"
          :height="110"
        />
      </VueFlow>
      <DiagramDetailPanel :selection="store.selection" @close="store.clearSelection()" @expand-group="(k) => expandGroup(`${GROUP_PREFIX}${k}`)" />
    </div>
  </div>
</template>

<style scoped>
/* UI-05: высота — окно минус фактическая шапка (--topbar-h публикует AppShell) и отступы контента. Раньше стояла
   константа 96 px: она не совпадала с реальной шапкой (документ получал +22 px на 900 и +59 px на 844), а 100vh на мобильных
   браузерах «прыгает» вместе с адресной строкой. Первое объявление height — запасное для браузеров без dvh. */
.diagram-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - var(--topbar-h, 68px) - var(--content-pad-top, 18px) - var(--content-pad-bottom, 32px));
  height: calc(100dvh - var(--topbar-h, 68px) - var(--content-pad-top, 18px) - var(--content-pad-bottom, 32px));
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.diagram-name-wrap {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: 4px;
}
.diagram-name {
  font-weight: 700;
  font-size: 14px;
}
.diagram-name-wrap .icon-btn {
  padding: 5px;
  color: var(--ink-muted);
}
.diagram-name-wrap .icon-btn .icon {
  width: 13px;
  height: 13px;
  display: block;
}
.diagram-name-wrap .icon-btn:hover {
  color: var(--ink);
}
.rename-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: 4px;
}
.rename-input {
  font-weight: 700;
  font-size: 14px;
  background: var(--surface-2);
  border: 1px solid var(--brand);
  border-radius: var(--r-s);
  padding: 3px 7px;
  color: var(--ink);
  font-family: inherit;
  min-width: 220px;
}
.rename-error {
  font-size: 10.5px;
  color: var(--status-crit);
}
.saving-hint {
  font-size: 11px;
  color: var(--ink-muted);
  font-style: italic;
}
.spacer {
  flex: 1;
}
.error-banner,
.loading-banner {
  padding: 20px;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.error-banner {
  color: var(--status-crit);
  display: flex;
  align-items: center;
  gap: 8px;
}
.canvas-wrap {
  position: relative;
  flex: 1 1 auto;
  /* Холст не сжимается в полоску, когда тулбар в несколько строк съедает высоту (низкий телефон в альбомной ориентации): лучше
     прокрутка страницы, чем диаграмма, которую нельзя разглядеть. */
  min-height: 320px;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
  background: var(--bg);
}
/* UI-22: подписи рёбер рисуются отдельным слоем (EdgeLabelRenderer) внутри холста, поэтому скрываются по классу на нём. */
.canvas-wrap.labels-hidden :deep(.diagram-edge-label) {
  display: none;
}
/* Мини-карта — справа от кнопок масштаба (оба в левом нижнем углу), чтобы не оказаться под панелью сведений справа. Стили
   пакета светлые (#fff), поэтому фон, рамка и «шторка» вне вида берутся из токенов темы. */
.canvas-wrap :deep(.vue-flow__minimap) {
  margin-left: 66px;
  background-color: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
}
.canvas-wrap :deep(.vue-flow__minimap-mask) {
  fill: color-mix(in srgb, var(--bg) 72%, transparent);
  stroke: var(--brand);
}
</style>
