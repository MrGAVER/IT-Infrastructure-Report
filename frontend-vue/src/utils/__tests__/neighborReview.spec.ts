import { describe, expect, it } from 'vitest'
import type { InterfaceConnectionDraft } from '../../api/types'
import type { ConnectionBaseline } from '../interfaceConnections'
import { buildReviewItems, collectReviewEntries, reviewPeerTarget, type ReviewPeers } from '../neighborReview'
import { portConfigOf } from '../portConflicts'
import { makeRow } from './interfaceRowFixture'

const remote = (patch: Partial<InterfaceConnectionDraft> = {}): InterfaceConnectionDraft => ({
  peer_device_id: 'dev-2',
  peer_interface_id: 'p1',
  connection_type_id: '',
  description: '',
  peer_device_name: 'sw-02',
  peer_interface_name: 'Gi0/9',
  ...patch,
})
const selfLink = (peer: string): InterfaceConnectionDraft =>
  remote({ peer_device_id: 'dev-1', peer_interface_id: peer, peer_device_name: undefined, peer_interface_name: undefined })
const noBaseline: ConnectionBaseline = new Map()

describe('collectReviewEntries', () => {
  it('сохранённый порт без изменений конфигурации и подключения не проверяется', () => {
    const row = makeRow({ id: 'a', connection: remote() })
    const baseline: ConnectionBaseline = new Map([['a', remote()]])
    const initial = new Map([['a', portConfigOf(row)]])
    expect(collectReviewEntries([row], initial, baseline, 'dev-1')).toEqual([])
  })

  it('порт, чья конфигурация отличается от снимка при открытии формы, проверяется', () => {
    const row = makeRow({ id: 'a', is_management: true, connection: remote() })
    const baseline: ConnectionBaseline = new Map([['a', remote()]])
    const initial = new Map([['a', portConfigOf(makeRow({ id: 'a' }))]])
    const entries = collectReviewEntries([row], initial, baseline, 'dev-1')
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      rowRef: 'a',
      peer: { ref: 'p1', isSelf: false, deviceId: 'dev-2', interfaceId: 'p1', nameHint: 'Gi0/9', deviceNameHint: 'sw-02' },
    })
  })

  it('новый порт и порт с заменённым подключением проверяются, строки без подключения или соседа — нет', () => {
    const created = makeRow({ key: 'k1', connection: remote() })
    const replaced = makeRow({ id: 'b', connection: remote({ peer_interface_id: 'p2' }) })
    const noPeer = makeRow({ id: 'c', connection: remote({ peer_interface_id: '' }) })
    const noConnection = makeRow({ id: 'd' })
    const baseline: ConnectionBaseline = new Map([['b', remote({ peer_interface_id: 'p1' })]])
    const initial = new Map([['b', portConfigOf(replaced)]])
    const entries = collectReviewEntries([created, replaced, noPeer, noConnection], initial, baseline, 'dev-1')
    expect(entries.map((e) => e.rowRef)).toEqual(['row:k1', 'b'])
  })

  it('два порта этого устройства, соединённые друг с другом, — одно расхождение', () => {
    const a = makeRow({ id: 'a', connection: selfLink('b') })
    const b = makeRow({ id: 'b', connection: selfLink('a') })
    const entries = collectReviewEntries([a, b], new Map(), noBaseline, 'dev-1')
    expect(entries).toHaveLength(1)
    expect(entries[0].peer).toMatchObject({ isSelf: true, deviceId: undefined })
  })

  it('у создаваемого устройства (без id) сосед-«это устройство» определяется по ключу строки', () => {
    const a = makeRow({ key: 'k1', connection: { ...selfLink(''), peer_row_key: 'k2' } })
    const entries = collectReviewEntries([a, makeRow({ key: 'k2' })], new Map(), noBaseline, null)
    expect(entries[0].peer).toMatchObject({ ref: 'row:k2', isSelf: true })
  })
})

describe('reviewPeerTarget', () => {
  const peers: ReviewPeers = { p1: { name: 'Gi0/9', config: { is_management: true, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: false } } }

  it('сосед-строка этой формы: подпись с номером строки и актуальная конфигурация из формы', () => {
    const rows = [makeRow({ id: 'a' }), makeRow({ id: 'b', name: 'Gi0/2', is_management: true })]
    const target = reviewPeerTarget({ ref: 'b', isSelf: true }, rows, {})
    expect(target).toMatchObject({ label: '«Gi0/2» (это устройство, строка 2)', isSelf: true, interfaceId: 'b' })
    expect(target?.config.is_management).toBe(true)
  })

  it('сосед-строка, которую убрали из формы, — null', () => {
    expect(reviewPeerTarget({ ref: 'zzz', isSelf: true }, [makeRow({ id: 'a' })], {})).toBeNull()
  })

  it('порт другого устройства берётся из загруженных данных; пока их нет — null', () => {
    const peer = { ref: 'p1', isSelf: false, deviceId: 'dev-2', interfaceId: 'p1', nameHint: 'Gi0/9', deviceNameHint: 'sw-02' }
    expect(reviewPeerTarget(peer, [], peers)).toMatchObject({ label: '«Gi0/9» (sw-02)', interfaceId: 'p1', isSelf: false })
    expect(reviewPeerTarget(peer, [], {})).toBeNull()
    expect(reviewPeerTarget({ ref: 'p1', isSelf: false, interfaceId: 'p1' }, [], peers)?.label).toBe('«Gi0/9» (другое устройство)')
  })
})

describe('buildReviewItems', () => {
  const entry = { rowRef: 'a', peer: { ref: 'p1', isSelf: false, deviceId: 'dev-2', interfaceId: 'p1' } }
  const peerConfig = { is_management: true, is_data_transfer: false, vlan_mode: 'access' as const, all_vlans: false }

  it('расхождение остаётся в списке, пока конфигурации различаются, и исчезает, когда совпали', () => {
    const rows = [makeRow({ id: 'a', is_management: false })]
    const items = buildReviewItems([entry], rows, { p1: { name: 'Gi0/9', config: peerConfig } })
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ key: 'a>p1', index: 0, kinds: ['flags'] })
    expect(items[0].texts[0]).toContain('«Управление»')
    const fixed = [makeRow({ id: 'a', is_management: true })]
    expect(buildReviewItems([entry], fixed, { p1: { name: 'Gi0/9', config: peerConfig } })).toEqual([])
  })

  it('запись пропускается, если строку убрали из формы или данных соседа ещё нет', () => {
    expect(buildReviewItems([entry], [makeRow({ id: 'zzz' })], { p1: { name: 'x', config: peerConfig } })).toEqual([])
    expect(buildReviewItems([entry], [makeRow({ id: 'a' })], {})).toEqual([])
  })
})
