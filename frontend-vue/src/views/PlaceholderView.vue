<script setup lang="ts">
withDefaults(defineProps<{ title: string; sheet?: string }>(), { sheet: '' })
</script>

<template>
  <div class="placeholder card">
    <svg class="icon"><use href="/icons.svg#i-box" /></svg>
    <h2>{{ title }}</h2>
    <p v-if="sheet">{{ sheet }} регламентного отчёта — данные пока читаются из текущего vanilla-интерфейса.</p>
    <p>Этот раздел ещё не перенесён на новый стек (Vue 3 + TypeScript). Экран «Инвентаризация устройств» — рабочий пример полной реализации на новой архитектуре.</p>
  </div>
</template>

<style scoped>
.placeholder {
  padding: 48px 24px;
  text-align: center;
  color: var(--ink-muted);
  max-width: 480px;
  margin: 40px auto;
}
.placeholder .icon {
  width: 32px;
  height: 32px;
  margin-bottom: 12px;
  color: var(--brand);
}
.placeholder h2 {
  font-family: var(--font-display);
  color: var(--ink);
  margin: 0 0 10px;
  font-size: 17px;
}
.placeholder p {
  font-size: 12.5px;
  line-height: 1.6;
  margin: 4px 0;
}
</style>
