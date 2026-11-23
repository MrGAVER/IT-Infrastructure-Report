// Вопрос «запись изменили, пока вы её редактировали — что делать?» из любого места приложения. Форма, получившая 409 STALE_RECORD,
// спрашивает пользователя через ask() и ждёт ответа; окно с вопросом живёт не в форме, а в StaleRecordHost (layout/AppShell.vue) — так же,
// как окно плана согласования портов (usePortSyncPlanRequest). Состояние общее на всё приложение: одновременно открыт один вопрос.
import { ref } from 'vue'

/**
 * overwrite — сохранить свои правки поверх чужих (прежнее поведение «выигрывает последняя запись», но теперь по явному решению);
 * reload — отказаться от своих правок: форма закроется, список обновится свежими данными; stay — остаться в форме и ничего не сохранять.
 */
export type StaleRecordChoice = 'overwrite' | 'reload' | 'stay'

export interface StaleRecordQuestion {
  /** Текст сервера («Запись изменена другим пользователем…»). */
  message: string
}

const question = ref<StaleRecordQuestion | null>(null)
let answer: ((choice: StaleRecordChoice) => void) | null = null

/**
 * @example
 * const choice = await useStaleRecordConflict().ask(error.message)
 * if (choice === 'overwrite') await saveWithoutCheck()
 */
export function useStaleRecordConflict() {
  return {
    question,
    ask(message: string): Promise<StaleRecordChoice> {
      // Предыдущий вопрос, оставшийся без ответа, закрываем как «остаться», чтобы его await не повис навсегда.
      answer?.('stay')
      question.value = { message }
      return new Promise((resolve) => {
        answer = resolve
      })
    },
    resolve(choice: StaleRecordChoice) {
      const pending = answer
      answer = null
      question.value = null
      pending?.(choice)
    },
  }
}
