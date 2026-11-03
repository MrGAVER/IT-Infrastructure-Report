<script setup lang="ts">
// Обёртка таблицы с горизонтальной прокруткой и подсказкой о ней (UI-06): у края, за которым есть ещё колонки, содержимое
// плавно затухает (mask-image), а на телефоне пользователь видит, что таблицу можно листать вбок.
//
// Затухание — маска самого контейнера: в отличие от `background-attachment: local` она не пропадает под фоном ячеек шапки и
// не зависит от их заливки. Когда таблица помещается целиком (десктоп), флаги false и вид не меняется. Прокручиваемый
// контейнер получает tabindex=0, чтобы его можно было листать стрелками с клавиатуры (правило axe scrollable-region-focusable).
import { onUpdated, ref } from 'vue'
import { useScrollShadow } from '../composables/useScrollShadow'

withDefaults(defineProps<{ label?: string }>(), { label: 'Таблица' })

const wrap = ref<HTMLElement | null>(null)
const { canScrollLeft, canScrollRight, update } = useScrollShadow(wrap)
// Строки добавились/удалились или таблица перерисовалась — ширина содержимого могла измениться.
onUpdated(update)
</script>

<template>
  <div
    ref="wrap"
    class="table-wrap"
    :class="{ 'shade-left': canScrollLeft, 'shade-right': canScrollRight }"
    role="region"
    :aria-label="label"
    :tabindex="canScrollLeft || canScrollRight ? 0 : undefined"
    @scroll.passive="update"
  >
    <slot />
  </div>
</template>

<style scoped>
.table-wrap {
  overflow-x: auto;
}
/* Ширина затухающей полосы. Меньше — подсказка незаметна, больше — перекрывает полезную колонку. */
.table-wrap.shade-right {
  -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);
  mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);
}
.table-wrap.shade-left {
  -webkit-mask-image: linear-gradient(to left, #000 calc(100% - 28px), transparent);
  mask-image: linear-gradient(to left, #000 calc(100% - 28px), transparent);
}
.table-wrap.shade-left.shade-right {
  -webkit-mask-image: linear-gradient(to right, transparent, #000 28px, #000 calc(100% - 28px), transparent);
  mask-image: linear-gradient(to right, transparent, #000 28px, #000 calc(100% - 28px), transparent);
}
.table-wrap:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}
</style>
