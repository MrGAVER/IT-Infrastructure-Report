// Директива v-write-only: скрывает элемент от ролей без права записи (viewer при включённой
// аутентификации), см. authStore.canWrite — единый источник правды для интерфейса.
//
// Скрывает через display: none, а не удаляет узел из DOM: для кнопок, которых у viewer'а не должно быть
// вообще, надёжнее `v-if="auth.canWrite"` (элемента нет в разметке и в доступном дереве). Директива
// нужна там, где условный рендер неудобен — например, на корне компонента, чьё содержимое нельзя менять.
// Это только UX-уровень: данные защищает сервер (403 на запись), а не скрытая кнопка.
//
// @example
// <button v-write-only @click="openCreate">Добавить</button>
import type { Directive } from 'vue'
import { useAuthStore } from '../stores/auth'

export const vWriteOnly: Directive<HTMLElement> = {
  mounted(el) {
    if (!useAuthStore().canWrite) el.style.display = 'none'
  },
  updated(el) {
    el.style.display = useAuthStore().canWrite ? '' : 'none'
  },
}
