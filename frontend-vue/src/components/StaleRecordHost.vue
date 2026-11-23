<script setup lang="ts">
// Окно конфликта версий: запись, которую пользователь редактирует, успели изменить (409 STALE_RECORD). Показывается поверх открытой формы
// по запросу useStaleRecordConflict.ask(); ничего не записывает само — только возвращает выбор форме, ждущей ответа.
import { useId } from 'vue'
import BaseModal from './BaseModal.vue'
import { useStaleRecordConflict } from '../composables/useStaleRecordConflict'

const { question, resolve } = useStaleRecordConflict()
// Доступное имя диалога — его заголовок: скринридер озвучивает название при открытии окна.
const titleId = useId()
</script>

<template>
  <template v-if="question">
    <BaseModal align="center" data-testid="stale-record" @close="resolve('stay')">
      <div class="dialog card" role="alertdialog" aria-modal="true" :aria-labelledby="titleId">
        <h3 :id="titleId">Запись изменили, пока вы её редактировали</h3>
        <p class="lead" data-testid="stale-record-message">{{ question.message }}</p>
        <ul class="options">
          <li><b>Сохранить мои изменения</b> — запись целиком заменится значениями из вашей формы, чужая правка будет потеряна.</li>
          <li><b>Загрузить свежие данные</b> — форма закроется без сохранения, список обновится; откройте запись заново.</li>
          <li><b>Остаться в форме</b> — ничего не сохраняется, вы можете скопировать свои значения.</li>
        </ul>
        <div class="foot">
          <button type="button" class="btn btn-secondary" data-testid="stale-record-stay" @click="resolve('stay')">Остаться в форме</button>
          <button type="button" class="btn btn-secondary" data-testid="stale-record-reload" @click="resolve('reload')">Загрузить свежие данные</button>
          <button type="button" class="btn btn-primary" data-testid="stale-record-overwrite" @click="resolve('overwrite')">Сохранить мои изменения</button>
        </div>
      </div>
    </BaseModal>
  </template>
</template>

<style scoped>
.dialog {
  width: 100%;
  max-width: 520px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h3 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.lead {
  font-size: 12.5px;
  margin: 0;
}
.options {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--ink-muted);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.foot {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
