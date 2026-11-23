import { describe, it, expect, vi } from 'vitest'
import { CONSISTENCY_LIMIT, entitySection, fetchConsistency, fetchConsistencyRules } from '../consistency'
import { finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'

describe('fetchConsistency', () => {
  it('читает все находки одним запросом с пределом сервера и возвращает отчёт как есть', async () => {
    const report = reportOf([finding()])
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(report)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchConsistency()).resolves.toEqual(report)

    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(new RegExp(`/integrity/consistency\\?limit=${CONSISTENCY_LIMIT}$`))
  })

  it('ошибку сервера не глотает: молчаливый сбой проверки выглядел бы как «данные в порядке»', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'Сбой' }), { status: 500 })),
    )
    await expect(fetchConsistency()).rejects.toThrow()
  })
})

describe('fetchConsistencyRules', () => {
  it('достаёт список правил из ответа каталога', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ rules: RULES })))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchConsistencyRules()).resolves.toEqual(RULES)
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/integrity\/consistency\/rules$/)
  })
})

describe('entitySection', () => {
  it.each([
    ['physical_device', '/devices'],
    ['virtual_machine', '/vms'],
    ['container', '/containers'],
    ['information_system', '/information-systems'],
  ])('%s ведёт в раздел %s', (type, path) => {
    expect(entitySection(type)?.to).toBe(path)
  })

  it('у объекта без своего раздела (IP-адрес, неизвестный тип) ссылки нет', () => {
    expect(entitySection('ip_address')).toBeNull()
    expect(entitySection('что-то-новое')).toBeNull()
  })
})
