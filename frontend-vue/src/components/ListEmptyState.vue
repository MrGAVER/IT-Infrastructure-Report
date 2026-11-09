<script setup lang="ts">
// Содержимое пустого списка (F-04 ревью main и его хвост): два разных случая не смешиваются.
//  - реестр пуст вовсе — «пока нет» и кнопка создания записи (новому пользователю с пустой базой ясно, что делать);
//  - записи есть, но поиск и фильтры ничего не оставили — «не найдено по заданным фильтрам» и кнопка «Сбросить фильтры».
//
// Компонент без обёртки: в таблице его кладёт в ячейку ListEmptyRow, а там, где список не таблица (карточки VLAN), — баннер экрана.
// Случай определяет вызывающий экран через registryEmpty: при пустом реестре фильтры ни на что не влияют, а при непустом пустой
// результат возможен только из-за них, поэтому отдельный признак «фильтры активны» не нужен.
// Кнопка создания показывается, только если передан actionLabel: экран не даёт его, когда у пользователя нет права записи
// или записи вообще не создают вручную (журнал аудита).
defineProps<{
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
  <div class="list-empty-state">
    <template v-if="registryEmpty">
      <p class="empty-text" data-empty="registry">{{ emptyText }}</p>
      <button v-if="actionLabel" type="button" class="btn btn-primary" data-action="create" @click="emit('action')">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        {{ actionLabel }}
      </button>
    </template>
    <template v-else>
      <p class="empty-text" data-empty="filtered">Ничего не найдено по заданным фильтрам.</p>
      <button type="button" class="btn btn-secondary" data-action="reset-filters" @click="emit('reset')">Сбросить фильтры</button>
    </template>
  </div>
</template>

<style scoped>
.empty-text {
  margin: 0 0 12px;
}
</style>
