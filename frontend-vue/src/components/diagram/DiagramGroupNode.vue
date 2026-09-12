<script setup lang="ts">
// Узел-группа — свёрнутое множество узлов (раздел 4.4/8 ТЗ). Клик разворачивает (обрабатывается
// в DiagramView.vue через @node-click, см. раздел 12 ТЗ, задача 3 Агента B: "разворачивание/
// сворачивание группы по клику").
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import type { DiagramGroupNode as DiagramGroupNodeData } from '../../api/diagrams'

const NODE_WIDTH = 160
const NODE_HEIGHT = 70

defineProps<NodeProps<DiagramGroupNodeData>>()
</script>

<template>
  <div class="diagram-group-node" :class="{ selected }" :style="{ width: `${NODE_WIDTH}px`, height: `${NODE_HEIGHT}px` }" :title="'Развернуть: ' + data.label">
    <Handle type="target" :position="Position.Top" />
    <Handle type="source" :position="Position.Bottom" />
    <svg class="icon"><use href="/icons.svg#i-layers" /></svg>
    <div class="label">{{ data.label }}</div>
  </div>
</template>

<style scoped>
.diagram-group-node {
  width: 100%;
  height: 100%;
  border-radius: var(--r-m, 10px);
  border: 1.5px dashed var(--ink-muted, #8fa0b3);
  background: var(--surface-2, #1e2c3b);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  cursor: pointer;
}
.diagram-group-node.selected {
  border-color: var(--brand, #33c9a7);
  box-shadow: 0 0 0 2px var(--brand-soft, rgba(51, 201, 167, 0.3));
}
.diagram-group-node .icon {
  width: 18px;
  height: 18px;
  color: var(--ink-muted, #8fa0b3);
}
.label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink, #e7edf3);
  text-align: center;
  padding: 0 8px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:deep(.vue-flow__handle) {
  opacity: 0;
}
</style>
