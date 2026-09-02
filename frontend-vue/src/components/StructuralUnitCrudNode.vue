<script setup lang="ts">
// Рекурсивный узел дерева структурных единиц с CRUD-действиями — отдельный от
// StructuralUnitTree.vue компонент, т.к. та версия заточена под чекбоксы-фильтры
// (см. DevicesView/ReportsView), а этой нужны кнопки добавить-потомка/редактировать/
// удалить и раскрытие по клику, а не через <details>.
import type { StructuralUnitNode } from '../stores/catalogs'

defineProps<{ node: StructuralUnitNode; depth: number }>()
const emit = defineEmits<{
  addChild: [parentId: string]
  edit: [node: StructuralUnitNode]
  remove: [node: StructuralUnitNode]
}>()
</script>

<template>
  <div class="unit">
    <div class="row" :style="{ paddingLeft: `${depth * 20 + 4}px` }">
      <span class="tree-guide" v-if="depth > 0">└</span>
      <span class="row-name">{{ node.name }}</span>
      <span v-if="node.description" class="row-desc">{{ node.description }}</span>
      <div class="row-actions">
        <button type="button" aria-label="Добавить дочернюю единицу" @click="emit('addChild', node.id)">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        </button>
        <button type="button" aria-label="Редактировать" @click="emit('edit', node)">
          <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
        </button>
        <button type="button" aria-label="Удалить" @click="emit('remove', node)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </div>
    <StructuralUnitCrudNode
      v-for="child in node.children"
      :key="child.id"
      :node="child"
      :depth="depth + 1"
      @add-child="(id) => emit('addChild', id)"
      @edit="(n) => emit('edit', n)"
      @remove="(n) => emit('remove', n)"
    />
  </div>
</template>

<script lang="ts">
export default { name: 'StructuralUnitCrudNode' }
</script>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px 9px 0;
  border-bottom: 1px solid var(--border);
}
.unit:last-child > .row {
  border-bottom: none;
}
.tree-guide {
  color: var(--ink-muted);
  font-size: 11px;
}
.row-name {
  font-weight: 600;
  font-size: 13px;
}
.row-desc {
  font-size: 11px;
  color: var(--ink-muted);
}
.row-actions {
  display: flex;
  gap: 2px;
  margin-left: auto;
}
.row-actions button {
  background: none;
  border: none;
  padding: 5px;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.row-actions button:hover {
  background: var(--surface-2);
  color: var(--ink);
}
.row-actions .icon {
  width: 13px;
  height: 13px;
  display: block;
}
</style>
