import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { useInterfaceRows } from '../useInterfaceRows'
import { useRowUiState } from '../useRowUiState'
import { useToast } from '../useToast'

function setup(initial: InterfaceDraftRow[], overrides: { managedOpenPorts?: boolean; editConnections?: boolean } = {}) {
  const rows = ref(initial)
  const ui = useRowUiState(() => rows.value.length)
  const api = useInterfaceRows(
    {
      rows: () => rows.value,
      setRows: (next) => {
        rows.value = next
      },
      knownVlans: () => [],
      protocolPortCatalog: () => [],
      editConnections: () => overrides.editConnections ?? false,
      rowManaged: () => ({ vlan: false, ip: false, openPorts: overrides.managedOpenPorts ?? false, subinterfaces: false }),
      groupLockNote: (_row, what) => `${what} задан группой`,
    },
    ui,
  )
  return { rows, ui, ...api }
}

const port = (id: string, name: string, openPorts: InterfaceDraftRow['open_ports'] = []) => makeRow({ id, name, open_ports: openPorts })
const open = (id: string | undefined, catalogId: string): InterfaceDraftRow['open_ports'][number] => ({
  id,
  protocol_catalog_id: catalogId,
  transport_protocol: 'tcp',
  description: '',
})

describe('useInterfaceRows', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    useToast().toasts.splice(0)
  })

  it('addRow добавляет пустую строку в конец и сбрасывает выбор; с editConnections строка получает ключ', () => {
    const { rows, ui, addRow } = setup([port('a', 'Gi0/1')], { editConnections: true })
    ui.toggleSelect(0, true)
    addRow()
    expect(rows.value).toHaveLength(2)
    expect(rows.value[1].name).toBe('')
    expect(rows.value[1].key).toBeTruthy()
    expect(ui.selectedIndices.value.size).toBe(0)
  })

  it('removeRow убирает строку, сбрасывает состояние списка и снимает ссылки на неё у соседей', () => {
    const link = { peer_device_id: '__self__', peer_interface_id: 'b', connection_type_id: '', description: '' }
    const { rows, ui, removeRow } = setup([makeRow({ id: 'a', connection: link }), port('b', 'Gi0/2')])
    ui.toggleExpand(0)
    removeRow(1)
    expect(rows.value.map((r) => r.id)).toEqual(['a'])
    expect(rows.value[0].connection?.peer_interface_id).toBe('')
    expect(ui.expandedIndices.value.size).toBe(0)
  })

  it('moveRowBy переставляет строку вместе с её выбором и раскрытием, а на границе ничего не делает', () => {
    const { rows, ui, moveRowBy } = setup([port('a', 'A'), port('b', 'B')])
    ui.toggleSelect(0, true)
    ui.toggleExpand(0)
    ui.setCopyTarget(0, '1')
    moveRowBy(0, 1)
    expect(rows.value.map((r) => r.id)).toEqual(['b', 'a'])
    expect([...ui.selectedIndices.value]).toEqual([1])
    expect([...ui.expandedIndices.value]).toEqual([1])
    expect(ui.copyTargetIndex.value).toEqual({})
    moveRowBy(0, -1)
    expect(rows.value.map((r) => r.id)).toEqual(['b', 'a'])
  })

  it('updateRow правит только свою строку, renamePort — имя строки', () => {
    const { rows, updateRow, renamePort } = setup([port('a', 'A'), port('b', 'B')])
    updateRow(1, { description: 'uplink' })
    renamePort(0, 'Gi0/9')
    expect(rows.value.map((r) => [r.name, r.description])).toEqual([
      ['Gi0/9', ''],
      ['B', 'uplink'],
    ])
    renamePort(5, 'нет такой строки')
    expect(rows.value).toHaveLength(2)
  })

  it('copyPortsTo копирует открытые порты без id, упорядочивая их, и сбрасывает выбор получателя', () => {
    const { rows, ui, copyPortsTo } = setup([port('a', 'A', [open('p1', 'c1')]), port('b', 'B')])
    ui.setCopyTarget(0, '1')
    copyPortsTo(0, 1)
    expect(rows.value[1].open_ports).toHaveLength(1)
    expect(rows.value[1].open_ports[0].id).toBeUndefined()
    expect(rows.value[0].open_ports[0].id).toBe('p1')
    expect(ui.copyTargetIndex.value[0]).toBe('')
    expect(useToast().toasts.at(-1)?.message).toContain('скопированы с «A» на «B»')
  })

  it('copyPortsTo: у получателя уже есть порты — спрашивает подтверждение, отказ оставляет всё как есть', () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const { rows, copyPortsTo } = setup([port('a', 'A', [open('p1', 'c1')]), port('b', 'B', [open('p2', 'c2')])])
    copyPortsTo(0, 1)
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(rows.value[1].open_ports[0].id).toBe('p2')
  })

  it('copyPortsTo: список открытых портов получателя задан группой — ошибка и без изменений; на себя и без портов — ничего', () => {
    const { rows, copyPortsTo } = setup([port('a', 'A', [open('p1', 'c1')]), port('b', 'B')], { managedOpenPorts: true })
    copyPortsTo(0, 1)
    expect(rows.value[1].open_ports).toEqual([])
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error' })
    expect(useToast().toasts.at(-1)?.message).toContain('Список открытых портов порта «B» задан группой')
    const second = setup([port('a', 'A', [open('p1', 'c1')]), port('b', 'B')])
    second.copyPortsTo(0, 0)
    second.copyPortsTo(1, 0)
    expect(second.rows.value[0].open_ports).toHaveLength(1)
  })

  it('applyCopyPorts берёт получателя из выбора строки и ничего не делает, пока он не выбран', () => {
    const { rows, ui, applyCopyPorts } = setup([port('a', 'A', [open('p1', 'c1')]), port('b', 'B')])
    applyCopyPorts(0)
    expect(rows.value[1].open_ports).toEqual([])
    ui.setCopyTarget(0, '1')
    applyCopyPorts(0)
    expect(rows.value[1].open_ports).toHaveLength(1)
  })
})
