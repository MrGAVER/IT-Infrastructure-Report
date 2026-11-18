<script setup lang="ts">
// Вынесено из DevicesView.vue (п.2 правки "инвентаризация физических устройств"): раньше
// разметка строки жила прямо в DevicesView.vue одним <tr v-for="d in devices.pageItems">.
// Теперь строк два вида — одиночное устройство и развёрнутый участник стека (с номером позиции
// вместо обычного индекса) — и оба используют ОДНУ И ТУ ЖЕ разметку столбцов, поэтому вынесена
// в отдельный компонент вместо дублирования полутора десятков <td> в двух местах DevicesView.vue.
import { useCatalogsStore } from '../stores/catalogs'
import { deviceModelLabel, devicePlaceLabel } from '../utils/deviceLabels'
import type { Device } from '../api/types'
import YesNoStatus from './YesNoStatus.vue'

defineProps<{
  device: Device
  /** Задан только для строки участника стека — номер позиции показывается вместо обычного
   * порядкового индекса и слегка отступает имя, чтобы визуально показать вложенность в стек. */
  stackPosition?: number | null
  /** true, пока это устройство удаляется (см. DevicesView.vue:removeDevice) — блокирует кнопку
   * удаления от повторного клика, пока запрос в процессе. */
  removing?: boolean
  /** Роль без права записи (viewer): вместо «Редактировать» — «Просмотр» (карточка откроется в режиме
   * просмотра), кнопок «Копировать» и «Удалить» нет. Задаётся родителем (authStore.canWrite). */
  readOnly?: boolean
}>()
defineEmits<{ edit: [d: Device]; copy: [d: Device]; remove: [d: Device] }>()

const catalogs = useCatalogsStore()

/** «Здание · помещение»: названия бывают в 100+ символов и раздували высоту строки, поэтому ячейка однострочная с многоточием,
 * а полный текст — в подсказке (title). Пустое значение в таблице показывается прочерком, а подсказки у него нет. */
function placeLabel(d: Device): string {
  return devicePlaceLabel(catalogs, d)
}
function modelLabel(d: Device): string {
  return deviceModelLabel(catalogs, d)
}
</script>

<template>
  <tr :class="{ 'stack-member-row': stackPosition != null }">
    <td class="type-tag">{{ catalogs.label('device-types', device.device_type_id) }}</td>
    <td>
      <span v-if="stackPosition != null" class="stack-pos" :title="`Позиция ${stackPosition} в стеке`">#{{ stackPosition }}</span>
      <span class="devname" :title="device.system_name || undefined">{{ device.system_name || '—' }}</span>
      <span v-if="device.description" class="devmodel" :title="device.description">{{ device.description }}</span>
    </td>
    <!-- Серийный номер не переносится посреди значения («SN-00011-/XXXX»): одна строка, у очень длинного — многоточие и title (UI-14). -->
    <td class="mono serial-cell">
      <span class="clip" :title="device.serial_number">{{ device.serial_number }}</span>
    </td>
    <td>
      <span class="clip clip-model" :title="modelLabel(device) || undefined">{{ modelLabel(device) || '—' }}</span>
    </td>
    <td>{{ device.embedded_os_name || catalogs.label('operating-systems', device.operating_system_id) }}</td>
    <td class="mono">{{ device.management_ips || '—' }}</td>
    <td>
      <span class="clip clip-place" :title="placeLabel(device) || undefined">{{ placeLabel(device) || '—' }}</span>
    </td>
    <td>
      <YesNoStatus :value="device.siem_enabled" />
    </td>
    <td>
      <div class="row-actions">
        <button type="button" :aria-label="readOnly ? 'Просмотр' : 'Редактировать'" @click="$emit('edit', device)">
          <svg class="icon"><use :href="readOnly ? '/icons.svg#i-file' : '/icons.svg#i-edit'" /></svg>
        </button>
        <button v-if="!readOnly" type="button" aria-label="Копировать" @click="$emit('copy', device)">
          <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
        </button>
        <button v-if="!readOnly" type="button" aria-label="Удалить" :disabled="removing" @click="$emit('remove', device)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </td>
  </tr>
</template>

<style scoped>
/* Базовая стилизация ячеек продублирована здесь намеренно: Vue scoped CSS не "пробрасывается"
   во вложенные элементы дочернего компонента — родительский DevicesView.vue видит только
   корневой <tr> этого компонента (может стилизовать его как элемент грида/списка), а вложенные
   <td> ему уже не подвластны. Раньше это была разметка ПРЯМО в DevicesView.vue, там эти же
   правила и были — теперь живут при своей разметке. */
td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: middle;
}
tr:last-child td {
  border-bottom: none;
}
tr:hover td {
  background: var(--surface-2);
}
.devname {
  font-weight: 600;
  display: block;
  max-width: 300px;
  /* Длинное имя без пробелов («sw-core-…-rack-12-unit-40») не раздувает колонку: переносится по любому символу. */
  overflow-wrap: anywhere;
}
/* Описание в две строки: десятки слов в описании делали строку таблицы выше экрана телефона (UI-06). Полный текст — в title. */
.devmodel {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  max-width: 300px;
  color: var(--ink-muted);
  font-size: 11.3px;
  margin-top: 1px;
}
/* Однострочная ячейка с многоточием. block + max-width, потому что у <td> max-width не работает надёжно. */
.clip {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.serial-cell {
  white-space: nowrap;
}
.serial-cell .clip {
  max-width: 28ch;
}
.clip-model {
  max-width: 220px;
}
.clip-place {
  max-width: 240px;
}
.type-tag {
  color: var(--ink-muted);
  font-size: 12px;
}
.stack-member-row td {
  background: var(--surface-2);
}
.stack-pos {
  display: inline-block;
  min-width: 22px;
  padding: 1px 5px;
  margin-right: 6px;
  border-radius: var(--r-s);
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--ink-muted);
  font-size: 10.5px;
  font-weight: 700;
  text-align: center;
}
.row-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.row-actions button {
  background: none;
  border: none;
  padding: 5px;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.row-actions button:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--ink);
}
.row-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.row-actions .icon {
  width: 14px;
  height: 14px;
  display: block;
}
</style>
