<script setup lang="ts">
withDefaults(defineProps<{ value: number | string; label: string; tone?: 'normal' | 'warn' }>(), {
  tone: 'normal',
})
</script>

<template>
  <div class="stat-card" :class="tone">
    <div class="num">{{ value }}</div>
    <div class="lbl">{{ label }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 13px 14px;
}
.num {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 22px;
  line-height: 1.1;
  color: var(--ink);
}
.lbl {
  font-size: 11px;
  color: var(--ink-muted);
  margin-top: 4px;
}
.stat-card.warn .num {
  color: var(--status-warn);
}
</style>
