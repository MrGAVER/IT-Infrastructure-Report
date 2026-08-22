<script setup lang="ts">
// Рекурсивный узел дерева структурных единиц. Выбор родителя в сторе устройств
// (stores/devices.ts:filtered) автоматически включает всех потомков — здесь
// компонент только отображает дерево и переключает конкретный id в v-model.
import type { StructuralUnitNode } from '../stores/catalogs'

const props = defineProps<{ nodes: StructuralUnitNode[]; selected: string[] }>()
const emit = defineEmits<{ toggle: [id: string] }>()

function isSelected(id: string) {
  return props.selected.includes(id)
}
</script>

<template>
  <ul class="tree-level">
    <li v-for="node in nodes" :key="node.id">
      <details v-if="node.children.length" open>
        <summary>
          <svg class="icon chev"><use href="/icons.svg#i-chevd" /></svg>
          <label @click.stop>
            <input type="checkbox" :checked="isSelected(node.id)" @change="emit('toggle', node.id)" />
            {{ node.name }}
          </label>
        </summary>
        <StructuralUnitTree :nodes="node.children" :selected="selected" @toggle="(id) => emit('toggle', id)" />
      </details>
      <label v-else class="leaf">
        <input type="checkbox" :checked="isSelected(node.id)" @change="emit('toggle', node.id)" />
        {{ node.name }}
      </label>
    </li>
  </ul>
</template>

<script lang="ts">
export default { name: 'StructuralUnitTree' }
</script>

<style scoped>
.tree-level {
  list-style: none;
  margin: 0;
  padding-left: 14px;
}
.tree-level:first-of-type {
  padding-left: 0;
}
summary {
  cursor: pointer;
  padding: 3px 0;
  display: flex;
  align-items: center;
  gap: 6px;
  list-style: none;
}
summary::-webkit-details-marker {
  display: none;
}
summary label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-weight: 600;
  font-size: 12px;
  color: var(--ink);
}
.chev {
  width: 12px;
  height: 12px;
  color: var(--ink-muted);
  transition: transform 0.15s;
}
details[open] > summary .chev {
  transform: rotate(0deg);
}
details:not([open]) > summary .chev {
  transform: rotate(-90deg);
}
.leaf {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 3px 0;
  font-size: 12px;
  color: var(--ink-muted);
}
input[type='checkbox'] {
  accent-color: var(--brand);
}
</style>
