// Режим «только просмотр» для форм-модалок: роль без права записи (viewer при включённой аутентификации,
// см. authStore.canWrite) может открыть карточку записи, но не менять её.
//
// Как применять в модалке: обернуть `<form>` в `<fieldset class="readonly-fieldset" :disabled="readOnly">`
// (браузер сам отключает все вложенные поля и кнопки, в том числе у дочерних компонентов), кнопку
// «Сохранить» показывать только при `!readOnly`, а в `submit()` выходить сразу при `readOnly.value`.
// Это UX-уровень: данные защищает сервер (403 на запись), а не отключённые поля.
//
// @example
// const { readOnly } = useReadOnlyForm()
// async function submit() { if (readOnly.value) return ... }
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

export function useReadOnlyForm() {
  const auth = useAuthStore()
  const readOnly = computed(() => !auth.canWrite)
  return { readOnly }
}
