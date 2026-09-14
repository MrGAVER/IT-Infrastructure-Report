<script setup lang="ts">
// Экран одной диаграммы топологии сети (раздел 11 ТЗ). @vue-flow/core — единственная новая
// рантайм-зависимость фронтенда (раздел 11 ТЗ) — без дополнительных пакетов @vue-flow/background
// и @vue-flow/controls: панорамирование/масштабирование колесом уже встроены в @vue-flow/core,
// доп. пакеты добавляют только декоративный фон и панель кнопок зума, без которых можно обойтись.
//
// localNodes/localEdges — v-model, привязанный к @vue-flow/core (это их задокументированный
// способ "управляемого" состояния канваса, см. README примеров пакета): библиотеке нужен
// СОБСТВЕННЫЙ реактивный массив, который она мутирует при драге/зуме, иначе перетаскивание узла
// не будет визуально плавным. Источник истины при этом остаётся стор (useDiagramStore) —
// localNodes/localEdges пересобираются из него заново при каждой загрузке/пересборке диаграммы
// (см. syncFromStore), а обратно в стор данные идут ТОЛЬКО через явные действия
// (onNodeDragStop -> store.moveNode, раздел 4.6 ТЗ), а не автоматической синхронизацией.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, type Edge, type EdgeMouseEvent, type Node, type NodeDragEvent, type NodeMouseEvent } from '@vue-flow/core'
import { useDiagramStore } from '../stores/diagram'
import { useToast } from '../composables/useToast'
import DiagramDeviceNode from '../components/diagram/DiagramDeviceNode.vue'
import DiagramGroupNode from '../components/diagram/DiagramGroupNode.vue'
import DiagramConnectionEdge from '../components/diagram/DiagramConnectionEdge.vue'
import DiagramDetailPanel from '../components/diagram/DiagramDetailPanel.vue'
import DiagramExportPanel from '../components/diagram/DiagramExportPanel.vue'
import { CONNECTION_EDGE_TYPE, GROUP_PREFIX, groupKeyOf, toFlowEdge, toFlowNode } from '../utils/diagramFlow'
import type { DiagramEdge, DiagramExportFormat, DiagramNode } from '../api/diagrams'

const route = useRoute()
const router = useRouter()
const store = useDiagramStore()
const { notify, notifyError } = useToast()
const { fitView } = useVueFlow()

const diagramId = computed(() => String(route.params.id))

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

async function loadAndFit() {
  await store.load(diagramId.value)
  syncFromStore()
  if (store.diagram) requestAnimationFrame(() => fitView())
}

onMounted(loadAndFit)
watch(diagramId, loadAndFit)

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
  if (data.type === 'group') {
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
  store.moveNode(node.id, node.position.x, node.position.y)
}

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
</script>

<template>
  <div class="diagram-view">
    <div class="toolbar">
      <button class="btn btn-secondary" type="button" @click="router.push({ name: 'diagrams' })">
        <svg class="icon"><use href="/icons.svg#i-chevd" style="transform: rotate(90deg)" /></svg>
        К списку
      </button>
      <span class="diagram-name">{{ store.diagram?.name }}</span>
      <span v-if="store.savingLayout" class="saving-hint">сохранение раскладки…</span>
      <div class="spacer"></div>
      <button class="btn btn-secondary" type="button" :disabled="store.loading" @click="onRegenerate">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Пересобрать
      </button>
      <button class="btn btn-secondary" type="button" @click="onDuplicate">Дублировать</button>
      <button class="btn btn-secondary" type="button" @click="onDelete">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        Удалить
      </button>
      <DiagramExportPanel :exporting="store.exporting" @export="onExport" />
    </div>

    <div v-if="store.error" class="error-banner card">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
      {{ store.error }}
    </div>
    <div v-else-if="store.loading && !store.diagram" class="loading-banner">Загрузка диаграммы…</div>

    <div v-else class="canvas-wrap">
      <VueFlow
        v-model:nodes="localNodes"
        v-model:edges="localEdges"
        :default-viewport="{ zoom: store.diagram?.viewport?.zoom ?? 1, x: store.diagram?.viewport?.pan_x ?? 0, y: store.diagram?.viewport?.pan_y ?? 0 }"
        :min-zoom="0.1"
        :max-zoom="2.5"
        :nodes-connectable="false"
        @node-click="onNodeClick"
        @edge-click="onEdgeClick"
        @pane-click="onPaneClick"
        @node-drag-stop="onNodeDragStop"
      >
        <template #node-device="nodeProps"><DiagramDeviceNode v-bind="nodeProps" /></template>
        <template #node-group="nodeProps"><DiagramGroupNode v-bind="nodeProps" /></template>
        <template #[`edge-${CONNECTION_EDGE_TYPE}`]="edgeProps"><DiagramConnectionEdge v-bind="edgeProps" /></template>
      </VueFlow>
      <DiagramDetailPanel :selection="store.selection" @close="store.clearSelection()" @expand-group="(k) => expandGroup(`${GROUP_PREFIX}${k}`)" />
    </div>
  </div>
</template>

<style scoped>
.diagram-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 96px);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.diagram-name {
  font-weight: 700;
  font-size: 14px;
  margin-left: 4px;
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
  flex: 1;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
  background: var(--bg);
}
</style>
