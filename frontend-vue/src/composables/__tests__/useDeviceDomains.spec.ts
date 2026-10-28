import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatalogItem, DeviceVlanDraftRow } from '../../api/types'
import { domain, makeDraft, setVlanDefinitions, setupStores, vlanDef } from './deviceFormTestkit'
import { useDeviceDomains } from '../useDeviceDomains'

const createResource = vi.fn()
const updateResource = vi.fn()
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  createResource: (...args: unknown[]) => createResource(...args),
  updateResource: (...args: unknown[]) => updateResource(...args),
}))

const row = (vlan_id: string, id?: string): DeviceVlanDraftRow => ({ id, vlan_id, ip_address: '', prefix_length: '', is_management: false, description: '' })

let stores: ReturnType<typeof setupStores>

function setup() {
  const draft = makeDraft()
  return { draft, domains: useDeviceDomains(draft) }
}

beforeEach(() => {
  vi.clearAllMocks()
  stores = setupStores()
  stores.domains.all = [domain('dom-1'), domain('dom-2'), domain('dom-3')]
  setVlanDefinitions(stores.vlans, [vlanDef('free-5', 5), vlanDef('a-10', 10, 'dom-1'), vlanDef('a-11', 11, 'dom-1'), vlanDef('b-20', 20, 'dom-2')])
})

describe('availableVlans — какие VLAN можно назначить устройству', () => {
  it('устройство ни в каком домене — только VLAN без домена', () => {
    const { domains } = setup()
    expect(domains.availableVlans.value.map((v) => v.id)).toEqual(['free-5'])
  })

  it('устройство в домене — только VLAN этого домена; сохранённое и отложенное членство учитываются вместе', () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1'])
    expect(domains.availableVlans.value.map((v) => v.id)).toEqual(['a-10', 'a-11'])
    draft.pendingDomainMemberships.value = new Set(['dom-2'])
    expect(domains.availableVlans.value.map((v) => v.id)).toEqual(['a-10', 'a-11', 'b-20'])
  })
})

describe('singleDeviceDomainId, joinableDomains, memberDomains', () => {
  it('singleDeviceDomainId — домен, только если он ровно один (с учётом отложенных)', () => {
    const { draft, domains } = setup()
    expect(domains.singleDeviceDomainId.value).toBeNull()
    draft.memberDomainIds.value = new Set(['dom-1'])
    expect(domains.singleDeviceDomainId.value).toBe('dom-1')
    draft.pendingDomainMemberships.value = new Set(['dom-2'])
    expect(domains.singleDeviceDomainId.value).toBeNull()
  })

  it('joinableDomains — домены, в которые устройство ещё не входит и не собирается войти', () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1'])
    draft.pendingDomainMemberships.value = new Set(['dom-2'])
    expect(domains.joinableDomains.value.map((d) => d.id)).toEqual(['dom-3'])
  })

  it('memberDomains — сохранённые, затем отложенные (pending); домены, которых нет в сторе, пропускаются', () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1', 'dom-ghost'])
    draft.pendingDomainMemberships.value = new Set(['dom-2', 'dom-1', 'dom-ghost-2'])
    expect(domains.memberDomains.value).toEqual([
      { id: 'dom-1', name: 'Домен dom-1', pending: false },
      { id: 'dom-2', name: 'Домен dom-2', pending: true },
    ])
  })
})

describe('onVlanCreated / onVlanDomainCreated', () => {
  it('создан VLAN чужого домена — стор VLAN перечитывается, домен ставится на отложенное включение', () => {
    const { draft, domains } = setup()
    domains.onVlanCreated({ id: 'new', domain_id: 'dom-2' } as unknown as CatalogItem)
    expect(stores.spies.vlansReload).toHaveBeenCalledTimes(1)
    expect([...draft.pendingDomainMemberships.value]).toEqual(['dom-2'])
  })

  it('VLAN без домена или уже подтверждённого домена членство не добавляет', () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1'])
    domains.onVlanCreated({ id: 'a', domain_id: null } as unknown as CatalogItem)
    domains.onVlanCreated({ id: 'b' } as unknown as CatalogItem)
    domains.onVlanCreated({ id: 'c', domain_id: 'dom-1' } as unknown as CatalogItem)
    expect(draft.pendingDomainMemberships.value.size).toBe(0)
    expect(stores.spies.vlansReload).toHaveBeenCalledTimes(3)
  })

  it('создан новый домен — он помечается источником синхронизации устройства, стор доменов перечитывается', () => {
    const { draft, domains } = setup()
    domains.onVlanDomainCreated({ id: 'dom-new' } as CatalogItem)
    expect([...draft.pendingSourceDomainIds.value]).toEqual(['dom-new'])
    expect(stores.spies.domainsReload).toHaveBeenCalledTimes(1)
  })
})

describe('onJoinDomainRequested', () => {
  it('домен встаёт в отложенные, стор VLAN перечитывается, VLAN домена добавляются в черновик по номеру', async () => {
    const { draft, domains } = setup()
    draft.deviceVlans.value = [row('free-5')]
    await domains.onJoinDomainRequested('dom-1')

    expect([...draft.pendingDomainMemberships.value]).toEqual(['dom-1'])
    expect(stores.spies.vlansReload).toHaveBeenCalledTimes(1)
    expect(draft.deviceVlans.value.map((r) => r.vlan_id)).toEqual(['free-5', 'a-10', 'a-11'])
  })

  it('повторное включение в тот же или уже подтверждённый домен ничего не делает', async () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1'])
    await domains.onJoinDomainRequested('dom-1')
    await domains.onJoinDomainRequested('dom-2')
    await domains.onJoinDomainRequested('dom-2')
    expect([...draft.pendingDomainMemberships.value]).toEqual(['dom-2'])
    expect(stores.spies.vlansReload).toHaveBeenCalledTimes(1)
  })

  it('если у домена нет новых VLAN, массив черновика остаётся прежним (тот же объект)', async () => {
    const { draft, domains } = setup()
    const rows = [row('b-20')]
    draft.deviceVlans.value = rows
    const before = draft.deviceVlans.value
    await domains.onJoinDomainRequested('dom-2')
    expect(draft.deviceVlans.value).toBe(before)
  })
})

describe('onCancelJoinDomain', () => {
  it('снимает отложенное включение и источник домена, убирает несохранённые VLAN домена; сохранённые строки остаются', () => {
    const { draft, domains } = setup()
    draft.pendingDomainMemberships.value = new Set(['dom-1', 'dom-2'])
    draft.pendingSourceDomainIds.value = new Set(['dom-1', 'dom-2'])
    draft.deviceVlans.value = [row('free-5'), row('a-10'), row('a-11', 'dv-1'), row('b-20')]

    domains.onCancelJoinDomain('dom-1')

    expect([...draft.pendingDomainMemberships.value]).toEqual(['dom-2'])
    expect([...draft.pendingSourceDomainIds.value]).toEqual(['dom-2'])
    expect(draft.deviceVlans.value.map((r) => r.vlan_id)).toEqual(['free-5', 'a-11', 'b-20'])
  })

  it('домен, которого нет среди отложенных (в том числе уже сохранённое членство), отменить нельзя', () => {
    const { draft, domains } = setup()
    draft.memberDomainIds.value = new Set(['dom-1'])
    draft.pendingSourceDomainIds.value = new Set(['dom-1'])
    draft.deviceVlans.value = [row('a-10')]
    domains.onCancelJoinDomain('dom-1')
    expect(draft.memberDomainIds.value.has('dom-1')).toBe(true)
    expect(draft.pendingSourceDomainIds.value.has('dom-1')).toBe(true)
    expect(draft.deviceVlans.value).toHaveLength(1)
  })
})

describe('persistPendingDomainMemberships', () => {
  it('создаёт связь с устройством для каждого отложенного домена и запоминает её', async () => {
    const { draft, domains } = setup()
    draft.pendingDomainMemberships.value = new Set(['dom-1', 'dom-2'])
    await domains.persistPendingDomainMemberships('dev-9')

    expect(createResource).toHaveBeenCalledTimes(2)
    expect(createResource).toHaveBeenCalledWith('vlan-domain-devices', { physical_device_id: 'dev-9', domain_id: 'dom-1' })
    expect(createResource).toHaveBeenCalledWith('vlan-domain-devices', { physical_device_id: 'dev-9', domain_id: 'dom-2' })
    expect([...draft.joinedDomainIds]).toEqual(['dom-1', 'dom-2'])
  })

  it('повтор после сбоя не создаёт уже созданные связи (POST не идемпотентен), недостающие дозаписывает', async () => {
    const { draft, domains } = setup()
    draft.pendingDomainMemberships.value = new Set(['dom-1', 'dom-2'])
    createResource.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('сбой'))
    await expect(domains.persistPendingDomainMemberships('dev-9')).rejects.toThrow('сбой')
    expect([...draft.joinedDomainIds]).toEqual(['dom-1'])

    createResource.mockResolvedValue({})
    await domains.persistPendingDomainMemberships('dev-9')
    expect(createResource).toHaveBeenCalledTimes(3)
    expect(createResource).toHaveBeenLastCalledWith('vlan-domain-devices', { physical_device_id: 'dev-9', domain_id: 'dom-2' })
  })

  it('без отложенных доменов ничего не отправляет', async () => {
    const { domains } = setup()
    await domains.persistPendingDomainMemberships('dev-9')
    expect(createResource).not.toHaveBeenCalled()
  })
})

describe('persistPendingSourceDomains', () => {
  it('делает устройство источником каждого заведённого здесь домена с автосинхронизацией (PUT, не POST)', async () => {
    const { draft, domains } = setup()
    draft.pendingSourceDomainIds.value = new Set(['dom-n1', 'dom-n2'])
    await domains.persistPendingSourceDomains('dev-9')

    expect(updateResource).toHaveBeenCalledTimes(2)
    expect(updateResource).toHaveBeenCalledWith('vlan-domains', 'dom-n1', { source_device_id: 'dev-9', auto_sync: true })
    expect(updateResource).toHaveBeenCalledWith('vlan-domains', 'dom-n2', { source_device_id: 'dev-9', auto_sync: true })
    expect(createResource).not.toHaveBeenCalled()
  })

  it('ошибка не глотается', async () => {
    const { draft, domains } = setup()
    draft.pendingSourceDomainIds.value = new Set(['dom-n1'])
    updateResource.mockRejectedValue(new Error('нет доступа'))
    await expect(domains.persistPendingSourceDomains('dev-9')).rejects.toThrow('нет доступа')
  })
})
