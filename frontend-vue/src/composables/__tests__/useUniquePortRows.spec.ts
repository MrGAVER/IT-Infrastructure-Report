import { describe, it, expect } from 'vitest'
import { ref } from 'vue'
import { duplicatePortsMessage, useUniquePortRows } from '../useUniquePortRows'
import type { ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'c-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'c-http', port: 80, protocol_type: 'HTTP', description: null },
  { id: 'c-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
  { id: 'c-https', port: 443, protocol_type: 'HTTPS', description: null },
]
const row = (protocol_catalog_id: string) => ({ protocol_catalog_id })

describe('useUniquePortRows', () => {
  it('подсвечивает строки с повторяющимся номером и даёт одно сообщение; реагирует на изменение строк', () => {
    const rows = ref([row('c-http'), row('c-ssh')])
    const { duplicateIndexes, duplicateMessage } = useUniquePortRows(
      () => rows.value,
      () => catalog,
    )
    expect(duplicateIndexes.value.size).toBe(0)
    expect(duplicateMessage.value).toBe('')

    rows.value = [row('c-http'), row('c-ssh'), row('c-http-alt')]

    expect([...duplicateIndexes.value].sort()).toEqual([0, 2])
    expect(duplicateMessage.value).toBe('Порт 80 указан несколько раз — каждый номер порта можно добавить только один раз.')
  })

  it('sortedForAdd упорядочивает по номеру порта, пустые строки — после заполненных; исходный массив не меняется', () => {
    const rows = [row('c-https'), row(''), row('c-ssh')]
    const { sortedForAdd } = useUniquePortRows(
      () => rows,
      () => catalog,
    )
    expect(sortedForAdd().map((r) => r.protocol_catalog_id)).toEqual(['c-ssh', 'c-https', ''])
    expect(rows.map((r) => r.protocol_catalog_id)).toEqual(['c-https', '', 'c-ssh'])
  })

  it('при выключенном правиле: порядок как ввёл пользователь, повторы не подсвечиваются', () => {
    const rows = [row('c-https'), row('c-http'), row('c-http-alt'), row('c-ssh')]
    const { duplicateIndexes, duplicateMessage, sortedForAdd } = useUniquePortRows(
      () => rows,
      () => catalog,
      () => false,
    )
    expect(sortedForAdd()).toBe(rows)
    expect(duplicateIndexes.value.size).toBe(0)
    expect(duplicateMessage.value).toBe('')
  })

  it('duplicatePortsMessage: несколько номеров через запятую, пустой список — пустая строка', () => {
    expect(duplicatePortsMessage([22, 80])).toContain('Порт 22, 80 указан несколько раз')
    expect(duplicatePortsMessage([])).toBe('')
  })
})
