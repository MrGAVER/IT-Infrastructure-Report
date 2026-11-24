import { describe, it, expect, vi } from 'vitest'
import {
  CONSISTENCY_LIMIT,
  approveFinding,
  entitySection,
  fetchConsistency,
  fetchConsistencyRules,
  fetchReportReadiness,
  findingTargets,
  isEditableEntity,
  revokeApproval,
} from '../consistency'
import { approvalOf, finding, READINESS, reportOf, RULES } from '../../__tests__/consistencyFixtures'

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

describe('approveFinding / revokeApproval', () => {
  it('одобрение уходит POST-ом с отпечатком и комментарием и возвращает ответ сервера', async () => {
    const answer = { created: true, approval: approvalOf({ comment: 'VRRP' }) }
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(answer)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(approveFinding('a'.repeat(64), 'VRRP')).resolves.toEqual(answer)

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/integrity\/consistency\/approvals$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ fingerprint: 'a'.repeat(64), comment: 'VRRP' })
  })

  it('отзыв — DELETE по id одобрения; id экранируется, пустой ответ 204 не ошибка', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(revokeApproval('a/b c')).resolves.toBeNull()

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/integrity\/consistency\/approvals\/a%2Fb%20c$/)
    expect(init.method).toBe('DELETE')
  })

  it('ошибку сервера (404: проблема уже изменилась) не глотает', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'Такой проблемы уже нет' }), { status: 404 })),
    )
    await expect(approveFinding('a'.repeat(64), null)).rejects.toMatchObject({ status: 404 })
  })
})

describe('findingTargets', () => {
  it('обычная находка — один объект с её именем и типом', () => {
    const item = finding({ entity_type: 'virtual_machine', entity_id: 'vm-1', entity_name: 'orphan' })
    expect(findingTargets(item)).toEqual([{ type: 'virtual_machine', id: 'vm-1', name: 'orphan' }])
  })

  it('повтор IP: объекты берутся из holders (устройство и ВМ), а не сам адрес', () => {
    const item = finding({
      details: {
        holders: [
          { entity_type: 'physical_device', entity_id: 'dev-1', name: 'srv-1', place: 'Gi0/1' },
          { entity_type: 'virtual_machine', entity_id: 'vm-1', name: 'vm-1', place: null },
        ],
      },
    })
    expect(findingTargets(item)).toEqual([
      { type: 'physical_device', id: 'dev-1', name: 'srv-1' },
      { type: 'virtual_machine', id: 'vm-1', name: 'vm-1' },
    ])
  })

  it('повтор системного имени: в devices тип не указан — это всегда устройства', () => {
    const item = finding({
      entity_type: 'physical_device',
      details: {
        devices: [
          { entity_id: 'dev-1', name: 'SW-1' },
          { entity_id: 'dev-2', name: 'SW-1' },
        ],
      },
    })
    expect(findingTargets(item).map((target) => [target.type, target.id])).toEqual([
      ['physical_device', 'dev-1'],
      ['physical_device', 'dev-2'],
    ])
  })

  it('мусор в details не ломает экран: записи без entity_id пропускаются, а имя по умолчанию — id', () => {
    const item = finding({ details: { holders: [null, 'x', { name: 'без id' }, { entity_type: 'container', entity_id: 'c-1' }] } })
    expect(findingTargets(item)).toEqual([{ type: 'container', id: 'c-1', name: 'c-1' }])
  })
})

describe('isEditableEntity', () => {
  it.each(['physical_device', 'virtual_machine', 'container', 'information_system'])('%s открывается в окне редактирования', (type) => {
    expect(isEditableEntity(type)).toBe(true)
  })

  it('IP-адрес и неизвестный тип окна редактирования не имеют', () => {
    expect(isEditableEntity('ip_address')).toBe(false)
    expect(isEditableEntity('что-то-новое')).toBe(false)
  })
})

describe('fetchReportReadiness', () => {
  it('читает готовность отчёта и возвращает ответ как есть', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(READINESS)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchReportReadiness()).resolves.toEqual(READINESS)
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/integrity\/consistency\/readiness$/)
  })

  it('ошибку сервера не глотает: сбой подсчёта не должен выглядеть как «отчёт готов»', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'Сбой' }), { status: 500 })),
    )
    await expect(fetchReportReadiness()).rejects.toThrow()
  })
})
