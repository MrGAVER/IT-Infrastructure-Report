<script setup lang="ts">
// Выбор количества строк на странице списка — в подвале таблицы рядом с пейджером.
// Варианты и запоминание выбора — utils/pageSize.ts, логика смены размера — в сторе списка.
defineProps<{ modelValue: number; options: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()

function onChange(event: Event) {
  emit('update:modelValue', Number((event.target as HTMLSelectElement).value))
}
</script>

<template>
  <label class="page-size">
    <span>Показывать по</span>
    <select :value="modelValue" aria-label="Количество строк на странице" @change="onChange">
      <option v-for="option in options" :key="option" :value="option">{{ option }}</option>
    </select>
  </label>
</template>

<style scoped>
.page-size {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.page-size select {
  height: 26px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--surface);
  color: var(--ink);
  font-size: 11.5px;
}
.page-size select:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}
</style>
