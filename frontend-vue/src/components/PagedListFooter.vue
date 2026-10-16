<script setup lang="ts">
// Подвал постраничного списка: «Показано 11–20 из 47», выбор размера страницы и номера страниц. Общий для экранов,
// у которых нет своей таблицы-подвала (VLAN, «Другие справочники»); состояние берётся из composables/usePagedList.ts.
import PageSizeSelect from './PageSizeSelect.vue'
import PagerNav from './PagerNav.vue'

defineProps<{
  page: number
  pageCount: number
  pageSize: number
  pageSizeOptions: number[]
  rangeFrom: number
  rangeTo: number
  total: number
}>()
defineEmits<{ 'update:page': [page: number]; 'update:pageSize': [size: number] }>()
</script>

<template>
  <div class="paged-foot">
    <span class="range">Показано {{ rangeFrom }}–{{ rangeTo }} из {{ total }}</span>
    <PageSizeSelect :model-value="pageSize" :options="pageSizeOptions" @update:model-value="$emit('update:pageSize', $event)" />
    <PagerNav :page="page" :page-count="pageCount" @update:page="$emit('update:page', $event)" />
  </div>
</template>

<style scoped>
.paged-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px;
  font-size: 11.5px;
  color: var(--ink-muted);
  gap: 12px;
  flex-wrap: wrap;
}
</style>
