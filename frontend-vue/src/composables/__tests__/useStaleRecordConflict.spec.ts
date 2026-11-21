import { beforeEach, describe, expect, it } from 'vitest'
import { useStaleRecordConflict } from '../useStaleRecordConflict'

describe('useStaleRecordConflict', () => {
  beforeEach(() => useStaleRecordConflict().resolve('stay'))

  it('ask показывает вопрос и возвращает выбор пользователя; после ответа вопрос закрыт', async () => {
    const { ask, resolve, question } = useStaleRecordConflict()
    const answer = ask('Запись изменена другим пользователем')

    expect(question.value).toEqual({ message: 'Запись изменена другим пользователем' })
    resolve('overwrite')

    await expect(answer).resolves.toBe('overwrite')
    expect(question.value).toBeNull()
  })

  it('состояние общее для всех вызовов: окно в AppShell отвечает форме, которая спросила', async () => {
    const answer = useStaleRecordConflict().ask('запись изменили')
    expect(useStaleRecordConflict().question.value?.message).toBe('запись изменили')
    useStaleRecordConflict().resolve('reload')
    await expect(answer).resolves.toBe('reload')
  })

  it('новый вопрос закрывает прежний, оставшийся без ответа, как «остаться»: await первой формы не повисает', async () => {
    const { ask, resolve, question } = useStaleRecordConflict()
    const first = ask('первая')
    const second = ask('вторая')

    await expect(first).resolves.toBe('stay')
    expect(question.value?.message).toBe('вторая')
    resolve('reload')
    await expect(second).resolves.toBe('reload')
  })

  it('resolve без вопроса ничего не ломает', () => {
    const { resolve, question } = useStaleRecordConflict()
    expect(() => resolve('overwrite')).not.toThrow()
    expect(question.value).toBeNull()
  })
})
