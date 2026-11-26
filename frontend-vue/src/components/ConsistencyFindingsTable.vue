<script setup lang="ts">
// Таблица находок проверки данных (ConsistencyView.vue): строка на проблему — важность, правило, объект, описание, лист и действия.
// Сама ничего не загружает и не меняет: родителю отдаются события («Одобрить», «Отозвать», нажатие на имя объекта, «Сбросить фильтры»).
import { computed } from 'vue'
import { CATEGORY_LABELS, SEVERITY_LABELS, SHEET_LABELS, entitySection, findingTargets, isEditableEntity } from '../api/consistency'
import type { ConsistencyFinding, EntityTarget } from '../api/consistency'
import { formatServerDateTime } from '../utils/dateTime'
import ListEmptyRow from './ListEmptyRow.vue'
import ScrollableTableWrap from './ScrollableTableWrap.vue'

const props = defineProps<{
  items: ConsistencyFinding[]
  /** Роль с правом записи: видит столбец «Действие», а имя объекта открывает окно редактирования. Наблюдателю имя — ссылка на раздел. */
  canWrite: boolean
  /** Идёт запрос на одобрение или отзыв: кнопки действий заблокированы. */
  busy: boolean
  /** Подгружается объект для окна редактирования: повторное нажатие на имя недоступно. */
  opening: boolean
  ruleTitle: (code: string) => string
  /** Фильтров нет: пустая таблица значит «проблем нет», а не «фильтры ничего не оставили». */
  registryEmpty: boolean
  emptyText: string
}>()

const emit = defineEmits<{
  approve: [item: ConsistencyFinding]
  revoke: [item: ConsistencyFinding]
  open: [target: EntityTarget]
  reset: []
}>()

const columnCount = computed(() => (props.canWrite ? 6 : 5))
const sheetLabel = (sheet: number) => SHEET_LABELS[sheet] ?? `Лист ${sheet}`
</script>

<template>
  <ScrollableTableWrap label="Находки проверки данных">
    <table>
      <thead>
        <tr>
          <th>Важность</th>
          <th>Что проверяли</th>
          <th>Объект</th>
          <th>Описание</th>
          <th>Лист отчёта</th>
          <th v-if="canWrite">Действие</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(item, index) in items" :key="`${item.rule}:${item.entity_id}:${index}`" :class="{ approved: item.approved }">
          <td>
            <span class="severity-badge" :class="item.severity">{{ SEVERITY_LABELS[item.severity] }}</span>
            <span v-if="item.approved" class="approved-badge">Одобрено</span>
          </td>
          <td>
            {{ ruleTitle(item.rule) }}
            <div class="category">{{ CATEGORY_LABELS[item.category] }}</div>
          </td>
          <td class="object-cell">
            <template v-for="(target, targetIndex) in findingTargets(item)" :key="`${target.type}:${target.id}`">
              <template v-if="targetIndex">, </template>
              <!-- Пишущему имя открывает окно редактирования; наблюдателю — ссылка на раздел (править он не может). -->
              <button
                v-if="canWrite && isEditableEntity(target.type)"
                type="button"
                class="entity-link"
                :disabled="opening"
                :title="`Открыть окно редактирования: ${target.name}`"
                @click="emit('open', target)"
              >
                {{ target.name }}
              </button>
              <router-link
                v-else-if="entitySection(target.type)"
                :to="entitySection(target.type)!.to"
                :title="`Открыть раздел «${entitySection(target.type)!.label}»`"
              >
                {{ target.name }}
              </router-link>
              <template v-else>{{ target.name }}</template>
            </template>
          </td>
          <td class="message-cell">
            {{ item.message }}
            <div v-if="item.approval" class="approval-note">
              Одобрено: {{ item.approval.approved_by ?? 'без учётной записи' }}, {{ formatServerDateTime(item.approval.approved_at) }}
              <template v-if="item.approval.comment"> — {{ item.approval.comment }}</template>
            </div>
          </td>
          <td>{{ item.sheet === null ? '—' : sheetLabel(item.sheet) }}</td>
          <td v-if="canWrite" class="action-cell">
            <button v-if="!item.approved" type="button" class="btn btn-secondary" :disabled="busy" @click="emit('approve', item)">Одобрить</button>
            <button v-else type="button" class="btn btn-secondary" :disabled="busy" @click="emit('revoke', item)">Отозвать одобрение</button>
          </td>
        </tr>
        <!-- Пустой результат — хорошая новость, а не «записей пока нет»: текст другой, кнопки создания нет. -->
        <ListEmptyRow v-if="!items.length" :colspan="columnCount" :registry-empty="registryEmpty" :empty-text="emptyText" @reset="emit('reset')" />
      </tbody>
    </table>
  </ScrollableTableWrap>
</template>

<style scoped>
.severity-badge {
  display: inline-flex;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.severity-badge.error {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.15));
  color: var(--crit-ink);
}
.severity-badge.warning {
  background: var(--status-warn-soft, rgba(232, 163, 61, 0.15));
  color: var(--status-warn);
}
.severity-badge.info {
  color: var(--brand-ink);
  background: var(--brand-soft);
}
.approved-badge {
  display: inline-flex;
  margin-left: 6px;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--status-ok, var(--brand-ink));
  background: var(--status-ok-soft, var(--brand-soft));
}
tr.approved td {
  opacity: 0.78;
}
.approval-note {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.entity-link {
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  font-weight: 500;
  color: var(--brand-ink);
  text-align: left;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
}
.entity-link:hover:not(:disabled) {
  text-decoration-style: solid;
}
.action-cell {
  white-space: nowrap;
}
.category {
  color: var(--ink-muted);
  font-size: 11px;
}
.object-cell {
  font-weight: 500;
}
.message-cell {
  min-width: 260px;
}
</style>
