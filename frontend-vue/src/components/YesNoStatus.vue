<script setup lang="ts">
// Статус «Да / Нет» для признаков покрытия (SIEM, СКЗИ) в таблицах устройств и информационных систем.
//
// «Да» — зелёный, как и раньше. «Нет» раньше светилось оранжевым (общий .status.off в base.css = «внимание»), и в столбце,
// где «Нет» у большинства строк, вся таблица выглядела тревожной (UI-12). Отсутствие признака — обычное состояние, а не
// сбой, поэтому «Нет» показывается нейтрально (приглушённый цвет текста). Точку-индикатор и размеры по-прежнему рисует
// глобальный .status из base.css; здесь переопределяется только цвет, чтобы не трогать общий файл стилей.
withDefaults(defineProps<{ value: boolean; yesLabel?: string; noLabel?: string }>(), {
  yesLabel: 'Да',
  noLabel: 'Нет',
})
</script>

<template>
  <span class="status" :class="value ? 'on' : 'off neutral'"> <span class="status-dot"></span>{{ value ? yesLabel : noLabel }} </span>
</template>

<style scoped>
.status.neutral {
  color: var(--ink-muted);
}
</style>
