<script setup lang="ts">
// Постраничная навигация подвала таблицы: «‹ 1 … 4 5 6 … 84 ›». При сотнях страниц нельзя рисовать
// кнопку на каждую — ряд вылезал за пределы карточки; окно номеров считает utils/pager.ts
// (первая, последняя и соседи текущей, пропуски — «…»). Страница хранится в сторе списка —
// компонент только показывает её и сообщает о выборе.
import { computed } from 'vue'
import { pagerItems } from '../utils/pager'

const props = defineProps<{ page: number; pageCount: number }>()
const emit = defineEmits<{ 'update:page': [page: number] }>()

const items = computed(() => pagerItems(props.page, props.pageCount))
</script>

<template>
  <nav class="pager" aria-label="Страницы">
    <button type="button" :disabled="page <= 1" aria-label="Предыдущая страница" @click="emit('update:page', page - 1)">‹</button>
    <template v-for="(item, i) in items" :key="`${item}-${i}`">
      <span v-if="item === '…'" class="pager-gap">…</span>
      <button
        v-else
        type="button"
        :class="{ on: item === page }"
        :aria-label="`Страница ${item}`"
        :aria-current="item === page ? 'page' : undefined"
        @click="emit('update:page', item)"
      >
        {{ item }}
      </button>
    </template>
    <button type="button" :disabled="page >= pageCount" aria-label="Следующая страница" @click="emit('update:page', page + 1)">›</button>
  </nav>
</template>

<style scoped>
.pager {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 100%;
}
.pager button {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--r-s);
  min-width: 26px;
  height: 26px;
  padding: 0 6px; /* номера из 4 цифр («1000») не помещаются в фиксированные 26px */
  color: var(--ink-muted);
}
.pager button.on {
  background: var(--brand);
  color: #05161c;
  border-color: var(--brand);
}
.pager button:disabled {
  opacity: 0.4;
}
.pager-gap {
  align-self: center;
  padding: 0 2px;
  color: var(--ink-muted);
}
</style>
