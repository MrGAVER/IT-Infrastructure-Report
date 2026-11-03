<script setup lang="ts">
import { computed } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

// to — необязательный переход: если задан, число становится ссылкой на соответствующий раздел
// (так дашборд ведёт от количества к списку). Без to карточка остаётся обычным блоком, как на
// остальных экранах со сводкой.
const props = withDefaults(defineProps<{ value: number | string; label: string; tone?: 'normal' | 'warn'; to?: RouteLocationRaw }>(), {
  tone: 'normal',
  to: undefined,
})

// tone="warn" — «на это стоит обратить внимание»: у счётчика нарушений ноль означает «всё в порядке», и оранжевый «0» у
// «Неактивные», «Расхождения», «ID с разными именами» ложно тревожил (UI-12). Поэтому предупреждение показывается только
// при значении больше нуля; нечисловое значение («—», пустая строка) тоже остаётся нейтральным.
const effectiveTone = computed(() => (props.tone === 'warn' && Number(props.value) > 0 ? 'warn' : 'normal'))
</script>

<template>
  <div class="stat-card" :class="effectiveTone">
    <router-link v-if="to" :to="to" class="num num-link" :title="`Открыть: ${label}`" :aria-label="`${label}: ${value}. Открыть раздел`">{{
      value
    }}</router-link>
    <div v-else class="num">{{ value }}</div>
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
.num-link {
  display: block;
  width: fit-content;
  text-decoration: none;
}
.stat-card .num-link:hover {
  color: var(--brand);
  text-decoration: underline;
}
.num-link:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
  border-radius: var(--r-s);
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
