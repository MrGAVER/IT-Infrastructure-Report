<script setup lang="ts">
import { computed } from 'vue'

// Постоянное (в отличие от toast, который гаснет через 10 с) сообщение о том, что данные загружены не полностью. Единая формулировка:
// - incomplete — экран показывает часть списка (усечённая загрузка listAllResource), остальное на нём не видно;
// - failed     — вложенный список формы не загрузился: он не показывается, и при сохранении с ним ничего не происходит;
// - partial    — вложенный список формы загружен не целиком: то же самое — иначе сохранение удалило бы невидимые записи.
// Для failed есть кнопка «Повторить загрузку» (событие retry); при partial повтор дал бы тот же результат, поэтому кнопки нет.
const props = defineProps<{
  kind: 'incomplete' | 'failed' | 'partial'
  /** Что загружалось, в родительном падеже: «контейнеров», «IP-адресов ВМ». */
  what: string
  loaded?: number
  total?: number
  /** Необязательное пояснение после основного текста: что ещё на экране считается по неполным данным. */
  hint?: string
}>()
defineEmits<{ retry: [] }>()

const format = (n: number | undefined) => (n ?? 0).toLocaleString('ru-RU')
const isError = computed(() => props.kind === 'failed')
</script>

<template>
  <div class="load-notice" :class="{ 'is-error': isError }" :role="isError ? 'alert' : 'status'" :data-kind="kind">
    <svg class="icon" aria-hidden="true"><use href="/icons.svg#i-alert" /></svg>
    <span v-if="kind === 'incomplete'">
      Показана часть данных ({{ what }}): загружено {{ format(loaded) }} из {{ format(total) }}. Остальные записи на этом экране не отображаются.
      {{ hint }}
    </span>
    <span v-else-if="kind === 'partial'">
      Загружена только часть данных ({{ what }}): {{ format(loaded) }} из {{ format(total) }}. Список не показывается, и при сохранении с ним ничего не
      произойдёт — иначе невидимые записи были бы удалены.
    </span>
    <span v-else>Не удалось загрузить данные ({{ what }}). Список не показывается, и при сохранении с ним ничего не произойдёт.</span>
    <button v-if="kind === 'failed'" type="button" class="btn btn-secondary" data-action="retry-load" @click="$emit('retry')">Повторить загрузку</button>
  </div>
</template>

<style scoped>
.load-notice {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  padding: 9px 12px;
  border: 1px solid var(--status-warn);
  border-radius: var(--r-m);
  background: var(--status-warn-soft);
  font-size: 12.5px;
  color: var(--ink);
}
.load-notice.is-error {
  border-color: transparent;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--crit-ink);
}
.load-notice .icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}
</style>
