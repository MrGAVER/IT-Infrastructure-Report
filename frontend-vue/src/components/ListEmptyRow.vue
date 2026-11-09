<script setup lang="ts">
// Строка таблицы списка, когда показывать нечего (F-04 ревью main). Само содержимое — ListEmptyState (общее с не табличными
// списками); здесь только ячейка на всю ширину таблицы. Правила двух случаев и кнопок описаны там.
import ListEmptyState from './ListEmptyState.vue'

defineProps<{
  /** Число столбцов таблицы — строка занимает их все. */
  colspan: number
  /** В реестре нет ни одной записи (а не «все отфильтрованы»). */
  registryEmpty: boolean
  /** Текст для пустого реестра, например «Устройств пока нет.». */
  emptyText: string
  /** Подпись кнопки создания, например «Добавить устройство»; без неё кнопки нет. */
  actionLabel?: string
}>()

const emit = defineEmits<{ action: []; reset: [] }>()
</script>

<template>
  <tr>
    <td :colspan="colspan" class="empty-row">
      <ListEmptyState :registry-empty="registryEmpty" :empty-text="emptyText" :action-label="actionLabel" @action="emit('action')" @reset="emit('reset')" />
    </td>
  </tr>
</template>

<style scoped>
.empty-row {
  text-align: center;
  color: var(--ink-muted);
  padding: 26px 14px;
}
</style>
