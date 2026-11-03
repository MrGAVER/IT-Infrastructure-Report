<script setup lang="ts">
// UI-02 (ревью 2.158.0): на холсте диаграммы не было ни кнопок масштаба, ни «вписать»; без колеса мыши или pinch-жеста
// масштабировать было нечем. Пакетный @vue-flow/controls не подошёл: у его кнопок нет aria-label, стили жёстко светлые
// (#fefefe), а подписи пришлось бы подменять слотами для каждой кнопки, теряя блокировку на пределах масштаба. Панель из трёх
// кнопок проще написать на токенах темы, чем перекрашивать чужую.
import { computed } from 'vue'
import { Panel, useVueFlow } from '@vue-flow/core'
import { FIT_VIEW_OPTIONS } from '../../utils/diagramViewport'

const ZOOM_ANIMATION_MS = 150
// Масштаб приходит дробным (2.4999 вместо 2.5 после серии нажатий) — допуск, чтобы кнопка гасла на пределе, а не на «почти пределе».
const ZOOM_EPSILON = 0.001

const { zoomIn, zoomOut, fitView, viewport, minZoom, maxZoom } = useVueFlow()
const atMaxZoom = computed(() => viewport.value.zoom >= maxZoom.value - ZOOM_EPSILON)
const atMinZoom = computed(() => viewport.value.zoom <= minZoom.value + ZOOM_EPSILON)
</script>

<template>
  <Panel position="bottom-left" class="diagram-zoom-controls" role="group" aria-label="Масштаб диаграммы">
    <button
      type="button"
      class="zoom-btn"
      aria-label="Увеличить масштаб"
      title="Увеличить масштаб"
      :disabled="atMaxZoom"
      @click="zoomIn({ duration: ZOOM_ANIMATION_MS })"
    >
      <svg class="icon" aria-hidden="true"><use href="/icons.svg#i-plus" /></svg>
    </button>
    <button
      type="button"
      class="zoom-btn"
      aria-label="Уменьшить масштаб"
      title="Уменьшить масштаб"
      :disabled="atMinZoom"
      @click="zoomOut({ duration: ZOOM_ANIMATION_MS })"
    >
      <svg class="icon" aria-hidden="true"><use href="/icons.svg#i-minus" /></svg>
    </button>
    <button
      type="button"
      class="zoom-btn"
      aria-label="Показать всю диаграмму"
      title="Показать всю диаграмму"
      @click="fitView({ ...FIT_VIEW_OPTIONS, duration: ZOOM_ANIMATION_MS })"
    >
      <svg class="icon" aria-hidden="true"><use href="/icons.svg#i-fit" /></svg>
    </button>
  </Panel>
</template>

<style scoped>
.diagram-zoom-controls {
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
}
.zoom-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  /* 36 px — минимальная удобная цель касания на телефоне; на десктопе кнопки от этого не выглядят крупными. */
  width: 36px;
  height: 36px;
  padding: 0;
  background: none;
  border: none;
  border-bottom: 1px solid var(--border);
  color: var(--ink);
}
.zoom-btn:last-child {
  border-bottom: none;
}
.zoom-btn:hover:not(:disabled) {
  background: var(--surface-2);
}
.zoom-btn:disabled {
  color: var(--ink-muted);
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
