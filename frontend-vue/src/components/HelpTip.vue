<script setup lang="ts">
// Кнопка "?" рядом с надписью поля — по клику показывает поясняющий текст (п.1.4.2: справка по
// использованию шаблона имени интерфейса). Сознательно НЕ переиспользует hover-тултип с
// секундной задержкой из v-truncate-tooltip (п.3) — это разные механизмы с разным назначением:
// truncate-tooltip показывает СВОЙ ЖЕ обрезанный текст поля при наведении, а HelpTip — заранее
// написанное пояснение по клику (работает и на touch-устройствах, где наведения не бывает).
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{ text: string }>()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)

function onDocumentClick(event: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(event.target as Node)) open.value = false
}
function onDocumentKeydown(event: KeyboardEvent) {
  // Esc закрывает только открытую подсказку и забирает событие (UI-04): иначе он закрыл бы ещё и окно, в котором она стоит.
  if (event.key !== 'Escape' || !open.value) return
  open.value = false
  event.preventDefault()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<template>
  <span ref="rootEl" class="help-tip">
    <button type="button" class="help-tip-btn" aria-label="Справка" :aria-expanded="open" @click="open = !open">?</button>
    <div v-if="open" class="help-tip-panel" role="tooltip">{{ text }}</div>
  </span>
</template>

<style scoped>
.help-tip {
  position: relative;
  display: inline-flex;
}
.help-tip-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
.help-tip-btn:hover {
  color: var(--ink);
  border-color: var(--ink-muted);
}
.help-tip-panel {
  position: absolute;
  z-index: 80;
  top: calc(100% + 6px);
  left: 0;
  width: max-content;
  max-width: 260px;
  padding: 8px 10px;
  border-radius: var(--r-s);
  border: 1px solid var(--border);
  background: var(--surface-1, var(--surface));
  box-shadow: var(--shadow-m, 0 4px 16px rgba(0, 0, 0, 0.25));
  color: var(--ink);
  font-size: 11.5px;
  font-weight: 400;
  line-height: 1.4;
  white-space: pre-line;
}
</style>
