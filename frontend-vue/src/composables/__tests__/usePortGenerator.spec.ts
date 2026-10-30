import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { emptyInterfaceRow } from '../../utils/interfaceRowDraft'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { usePortGenerator } from '../usePortGenerator'
import { useRowUiState } from '../useRowUiState'

function setup(initial: InterfaceDraftRow[]) {
  const rows = ref(initial)
  const ui = useRowUiState(() => rows.value.length)
  const generator = usePortGenerator(
    {
      rows: () => rows.value,
      setRows: (next) => {
        rows.value = next
      },
      knownVlans: () => [],
      emptyRow: () => emptyInterfaceRow(false),
    },
    ui,
  )
  return { rows, ui, generator }
}

describe('usePortGenerator', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
  })

  it('начальное количество — число уже загруженных строк', () => {
    expect(setup([makeRow(), makeRow()]).generator.genCount.value).toBe('2')
  })

  it('без галочки «Заменить все порты» новые порты добавляются в конец, нумерация продолжается, подтверждение не нужно', () => {
    const { rows, generator } = setup([makeRow({ id: 'a', name: 'eth1' })])
    generator.genCount.value = '2'
    generator.genTypeId.value = 't-1'
    generator.applyGenerator()
    expect(rows.value.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth3'])
    expect(rows.value[2].interface_type_id).toBe('t-1')
    expect(confirm).not.toHaveBeenCalled()
  })

  it('«Начать нумерацию с» задаёт первый номер, в том числе 0', () => {
    const { rows, generator } = setup([])
    generator.genCount.value = '2'
    generator.genStartAt.value = '5'
    generator.genNameTemplate.value = 'Gi0/{n0}'
    generator.applyGenerator()
    expect(rows.value.map((r) => r.name)).toEqual(['Gi0/05', 'Gi0/06'])
  })

  it('«Заменить все порты» спрашивает подтверждение, заменяет список и снимает галочку', () => {
    const { rows, ui, generator } = setup([makeRow({ id: 'a', name: 'old', vlan_ids: ['v10'] }), makeRow({ id: 'b', name: 'old2' })])
    ui.toggleSelect(0, true)
    generator.genCount.value = '1'
    generator.replaceAllPorts.value = true
    generator.applyGenerator()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(rows.value).toHaveLength(1)
    expect(rows.value[0]).toMatchObject({ id: 'a', name: 'eth1', vlan_ids: ['v10'] })
    expect(ui.selectedIndices.value.size).toBe(0)
    expect(generator.replaceAllPorts.value).toBe(false)
  })

  it('отказ в подтверждении оставляет список и галочку как есть', () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const { rows, generator } = setup([makeRow({ name: 'keep' })])
    generator.replaceAllPorts.value = true
    generator.applyGenerator()
    expect(rows.value.map((r) => r.name)).toEqual(['keep'])
    expect(generator.replaceAllPorts.value).toBe(true)
  })

  it('замена с количеством 0 предупреждает об удалении всех портов', () => {
    const { rows, generator } = setup([makeRow(), makeRow()])
    generator.genCount.value = '0'
    generator.replaceAllPorts.value = true
    generator.applyGenerator()
    expect(vi.mocked(confirm).mock.calls[0][0]).toContain('будут удалены')
    expect(rows.value).toEqual([])
  })

  it('«Дополнить» с нулевым или нечисловым количеством ничего не добавляет', () => {
    const { rows, generator } = setup([makeRow()])
    generator.genCount.value = '0'
    generator.applyGenerator()
    generator.genCount.value = 'abc'
    generator.applyGenerator()
    expect(rows.value).toHaveLength(1)
  })
})
