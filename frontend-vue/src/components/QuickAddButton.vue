<script setup lang="ts">
// Кнопка "+" рядом с select'ом справочника — открывает QuickAddModal.vue и по успешному
// сохранению эмитит созданную запись, чтобы вызывающая форма могла сразу подставить её id в
// свой select (см. использование в DeviceFormModal.vue и т.п.).
import { ref } from 'vue'
import QuickAddModal from './QuickAddModal.vue'
import type { CatalogItem } from '../api/types'
import type { QuickAddFkScope } from '../quickAdd/schema'

const props = defineProps<{ resource: string; title?: string; initialValues?: Record<string, string>; fkScope?: QuickAddFkScope }>()
const emit = defineEmits<{ created: [record: CatalogItem]; 'nested-created': [fieldName: string, fkResource: string, record: CatalogItem] }>()

const open = ref(false)

function onCreated(record: CatalogItem) {
  open.value = false
  emit('created', record)
}
</script>

<template>
  <button type="button" class="quick-add-btn" :aria-label="`Добавить: ${title ?? resource}`" @click="open = true">
    <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
  </button>
  <QuickAddModal
    v-if="open"
    :resource="resource"
    :initial-values="initialValues"
    :fk-scope="fkScope"
    @close="open = false"
    @created="onCreated"
    @nested-created="(fieldName, fkResource, record) => emit('nested-created', fieldName, fkResource, record)"
  />
</template>

<style scoped>
.quick-add-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--r-s);
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--ink-muted);
  cursor: pointer;
}
.quick-add-btn:hover {
  color: var(--brand);
  border-color: var(--brand);
}
.quick-add-btn .icon {
  width: 14px;
  height: 14px;
}
</style>
