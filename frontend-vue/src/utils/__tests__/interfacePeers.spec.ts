import { describe, expect, it } from 'vitest'
import { freedPeerIds, selfPortCandidates, takenPeerIds } from '../interfacePeers'
import type { ConnectionBaseline } from '../interfaceConnections'
import { makeRow } from './interfaceRowFixture'

const link = (peer: string) => ({ peer_device_id: '__self__', peer_interface_id: peer, connection_type_id: '', description: '' })

describe('takenPeerIds', () => {
  it('собирает соседей из других строк, но не из самой строки', () => {
    const rows = [makeRow({ id: 'a', connection: link('c') }), makeRow({ id: 'b', connection: link('d') }), makeRow({ id: 'c' })]
    expect([...takenPeerIds(rows, 0)]).toEqual(['d'])
    expect([...takenPeerIds(rows, 2)].sort()).toEqual(['c', 'd'])
  })

  it('учитывает и соседа-несохранённую строку (по ключу)', () => {
    const rows = [makeRow({ id: 'a', connection: { ...link(''), peer_row_key: 'k1' } }), makeRow({ id: 'b' })]
    expect([...takenPeerIds(rows, 1)]).toEqual(['row:k1'])
  })
})

describe('selfPortCandidates', () => {
  it('не предлагает саму строку и порты без возможности сослаться на них', () => {
    const rows = [makeRow({ id: 'a', name: 'Gi0/1' }), makeRow({ name: 'Gi0/2' }), makeRow({ id: 'c', name: '' })]
    const result = selfPortCandidates(rows, 0)
    expect(result.map((c) => c.value)).toEqual(['c'])
    expect(result[0].label).toBe('без имени (строка 3)')
  })

  it('не предлагает порты, уже выбранные соседом другой строки или имеющие своё подключение', () => {
    const rows = [makeRow({ id: 'a' }), makeRow({ id: 'b', connection: link('d') }), makeRow({ id: 'c' }), makeRow({ id: 'd' })]
    // b сама подключена к d; c свободна; d занята подключением строки b
    expect(selfPortCandidates(rows, 0).map((c) => c.value)).toEqual(['c'])
  })

  it('сосед, уже выбранный этой строкой, остаётся в списке', () => {
    const rows = [makeRow({ id: 'a', connection: link('b') }), makeRow({ id: 'b', connection: link('z') })]
    expect(selfPortCandidates(rows, 0).map((c) => c.value)).toEqual(['b'])
  })

  it('у несохранённой строки сосед описывается ключом строки, а не id', () => {
    const rows = [makeRow({ id: 'a' }), makeRow({ key: 'k7', name: 'Gi0/7' })]
    expect(selfPortCandidates(rows, 0)[0]).toMatchObject({ value: 'row:k7', rowKey: 'k7', interfaceId: undefined })
  })
})

describe('freedPeerIds', () => {
  const baseline: ConnectionBaseline = new Map([
    ['a', { peer_device_id: 'dev-2', peer_interface_id: 'p1', connection_type_id: '', description: '' }],
    ['b', null],
  ])

  it('без снимка подключений освобождать нечего', () => {
    expect(freedPeerIds([makeRow({ id: 'a' })], undefined).size).toBe(0)
  })

  it('порт соседа освобождается, когда подключение снято или переставлено на другой порт', () => {
    expect([...freedPeerIds([makeRow({ id: 'a', connection: null })], baseline)]).toEqual(['p1'])
    const moved = makeRow({ id: 'a', connection: { peer_device_id: 'dev-2', peer_interface_id: 'p2', connection_type_id: '', description: '' } })
    expect([...freedPeerIds([moved], baseline)]).toEqual(['p1'])
  })

  it('подключение не тронуто, порт без подключения в снимке и строка без id ничего не освобождают', () => {
    const same = makeRow({ id: 'a', connection: { peer_device_id: 'dev-2', peer_interface_id: 'p1', connection_type_id: '', description: '' } })
    expect(freedPeerIds([same, makeRow({ id: 'b' }), makeRow()], baseline).size).toBe(0)
  })
})
