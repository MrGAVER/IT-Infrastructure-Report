<script setup lang="ts">
// Общая основа всех модальных окон приложения (F-01 и F-03 кода-ревью main). Раньше подложка, закрытие по клику и по Esc и
// числа z-index копировались в каждое из 34 окон; теперь они здесь, и любая правка (фон, отступы, фокус) делается один раз.
//
// Что даёт окну:
//  — подложку `.modal-overlay` в <body> (Teleport): окно не зависит от transform/overflow предков и стоит над страницей;
//  — закрытие по клику на подложку (выделение текста, закончившееся над подложкой, окно не закрывает) и по Esc одним событием close;
//    из вложенных окон по Esc закрывается только верхнее — по тому же стеку, что и фокус;
//  — ловушку фокуса и возврат фокуса на кнопку, открывшую окно;
//  — блокировку прокрутки страницы под окном;
//  — слой: z-index = --z-modal + номер окна в стеке открытых окон, так что вложенное окно всегда выше родителя независимо от порядка
//    в DOM.
// Всё это — один вызов useModalLayer (composables/modalLayer.ts): порядок сторон и их связь со стеком окон там, а не здесь.
//
// Карточку диалога (`<div class="… card" role="dialog" aria-modal="true" aria-labelledby=…>`), заголовок и кнопки окно
// кладёт в слот само: у каждого окна своя ширина и своя раскладка, и стили карточки остаются в его собственном scoped-CSS.
// Имя диалога (aria-labelledby или aria-label) обязательно — это проверяет modalDialogs.spec.ts.
//
// @example
// <BaseModal @close="emit('close')">
//   <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId"> … </div>
// </BaseModal>
import { computed, inject, ref } from 'vue'
import { useModalLayer } from '../composables/modalLayer'
import { MODAL_TELEPORT_DISABLED } from './baseModalKeys'

// Атрибуты родителя (data-testid и т. п.) попадают на подложку, а не на Teleport, у которого корня-элемента нет.
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    /** top — окно у верхнего края (формы); center — по центру (короткие диалоги подтверждения). */
    align?: 'top' | 'center'
    /** Отступ окна от верхнего края для align="top", px. */
    offset?: number
  }>(),
  { align: 'top', offset: 40 },
)
const emit = defineEmits<{ close: [] }>()
// Тестовый переключатель Teleport (в приложении не задаётся — окно всегда в <body>), см. baseModalKeys.ts.
const teleportDisabled = inject(MODAL_TELEPORT_DISABLED, false)

const overlay = ref<HTMLElement | null>(null)
// Стек окон, Esc, закрытие по подложке, ловушка фокуса и блокировка прокрутки — одним вызовом, в нужном порядке (modalLayer.ts).
const { depth, onOverlayPointerDown, onOverlayClick } = useModalLayer({
  dialog: () => overlay.value?.querySelector<HTMLElement>('[role="dialog"], [role="alertdialog"]') ?? overlay.value,
  onClose: () => emit('close'),
})

const layerStyle = computed(() => ({ '--modal-depth': depth.value, '--modal-offset': `${props.offset}px` }))
</script>

<template>
  <Teleport to="body" :disabled="teleportDisabled">
    <div
      ref="overlay"
      v-bind="$attrs"
      class="modal-overlay"
      :class="{ 'modal-overlay--center': align === 'center' }"
      :style="layerStyle"
      @mousedown="onOverlayPointerDown"
      @click="onOverlayClick"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-modal) + var(--modal-depth, 0));
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: var(--modal-offset, 40px) 16px;
  background: var(--backdrop);
  overflow-y: auto;
  /* Колесо над окном, доехавшее до края, не должно прокручивать страницу позади. */
  overscroll-behavior: contain;
}
.modal-overlay--center {
  align-items: center;
  /* safe — окно выше экрана не обрезается сверху, а прокручивается; браузеры без safe берут обычный center. */
  align-items: safe center;
  padding: 16px;
}
/* Диалог получает фокус программно (tabindex="-1" ставит useFocusTrap): рамка у него не нужна — это не элемент управления. */
.modal-overlay :deep([role='dialog']:focus),
.modal-overlay :deep([role='alertdialog']:focus) {
  outline: none;
}
</style>
