<script setup lang="ts">
// Проверка расхождений с соседними портами при нажатии «Сохранить» формы устройства: список портов, чьи назначение, режим или
// «Все VLAN» отличаются от порта на другом конце подключения. Можно привести их к одному виду сейчас или сохранить как есть.
// Состояние окна и применение — usePreSaveReview; окно показывает пункты и сообщает о выборе. Стоит ДО окна последствий каскада
// режима порта (VlanModeCascadeModal): оно открывается из этого диалога и должно быть выше него.
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import type { ReviewItem } from '../utils/neighborReview'

defineProps<{
  items: ReviewItem[]
  /** Идёт применение конфигурации — кнопки применения недоступны. */
  busy: boolean
}>()
const emit = defineEmits<{
  /** Окно закрыто: proceed — сохранять форму (иначе вернуться к ней). */
  finish: [proceed: boolean]
  'apply-neighbor': [item: ReviewItem]
  'apply-current': [item: ReviewItem]
}>()

const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('finish', false))
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="conflict-modal review-modal card" role="alertdialog" aria-modal="true" aria-labelledby="neighbor-review-title">
      <div class="conflict-modal-head">
        <h3 id="neighbor-review-title">Настройки порта расходятся с соседним портом</h3>
        <button type="button" class="icon-btn" aria-label="Вернуться к форме" @click="emit('finish', false)">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <template v-if="items.length">
        <p class="conflict-modal-desc">
          Назначение («Управление» / «Передача данных»), режим порта (Trunk / Access) или «Все VLAN» отличается от настроек порта на другом конце подключения. Можно
          привести их к одному виду сейчас (для «Все VLAN» значение выбираете вы) или сохранить как есть — расхождение будет отмечено на экране «Подключения».
        </p>
        <ul class="review-list">
          <li v-for="item in items" :key="item.key" class="review-item">
            <div class="review-item-title">Порт «{{ item.row.name.trim() || 'без имени' }}» ↔ {{ item.peer.label }}</div>
            <div class="review-item-diffs">{{ item.texts.join('; ') }}</div>
            <div class="review-item-actions">
              <button type="button" class="btn btn-secondary" :disabled="busy" title="Этому порту — назначение, режим порта и «Все VLAN» соседа" @click="emit('apply-neighbor', item)">
                Применить конфигурацию соседа
              </button>
              <button type="button" class="btn btn-secondary" :disabled="busy" title="Соседу — назначение, режим порта и «Все VLAN» этого порта" @click="emit('apply-current', item)">
                Применить текущую конфигурацию
              </button>
            </div>
            <small v-if="!item.peer.isSelf" class="review-item-note">Сосед — порт другого устройства: его настройки изменятся сразу, не дожидаясь сохранения формы.</small>
          </li>
        </ul>
      </template>
      <p v-else class="conflict-modal-desc review-done">Расхождений не осталось.</p>
      <div class="review-footer">
        <button type="button" class="btn btn-secondary" @click="emit('finish', false)">Вернуться к форме</button>
        <button type="button" class="btn btn-primary" @click="emit('finish', true)">{{ items.length ? 'Сохранить как есть' : 'Сохранить' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped src="../styles/interfaceModal.css"></style>
<style scoped>
.review-modal {
  max-width: 560px;
  max-height: 85vh;
  overflow-y: auto;
}
.review-list {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.review-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.review-item-title {
  font-size: 12.5px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.review-item-diffs {
  font-size: 12px;
  color: var(--status-warn);
}
.review-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.review-item-actions .btn {
  padding: 5px 9px;
  font-size: 11.5px;
}
.review-item-note {
  font-size: 11px;
  color: var(--ink-muted);
}
.review-done {
  color: var(--ink);
}
.review-footer {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
