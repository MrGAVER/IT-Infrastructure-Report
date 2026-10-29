import { describe, expect, it } from 'vitest'
import type { VLANDefinition } from '../../api/types'
import { allVlansDiffer, carriesAllVlans, describeVlanValue, isAllVlansSelected, pickerSelection, toggleValueAll, toggleValueVlan, valueFromSource } from '../allVlans'

const vlan = (id: string, number: number): VLANDefinition => ({ id, vlan_id: number, name: `VLAN ${number}`, description: '', domain_id: null, domain_name: '', devices: [] })
const options = [vlan('a10', 10), vlan('a20', 20), vlan('a30', 30)]

describe('isAllVlansSelected', () => {
  it('галочка «Все VLAN» — это сохраняемый признак порта, а не вывод из набора выбранных VLAN', () => {
    expect(isAllVlansSelected({ all_vlans: true })).toBe(true)
    expect(isAllVlansSelected({ all_vlans: false })).toBe(false)
    expect(isAllVlansSelected({})).toBe(false)
  })

  it('режим порта не проверяется (в отличие от carriesAllVlans): отмечена ли галочка, решает один признак', () => {
    expect(isAllVlansSelected({ all_vlans: true, vlan_mode: 'access' } as { all_vlans: boolean })).toBe(true)
    expect(carriesAllVlans({ all_vlans: true, vlan_mode: 'access' })).toBe(false)
  })
})

describe('carriesAllVlans / allVlansDiffer', () => {
  it('признак значим только в trunk', () => {
    expect(carriesAllVlans({ vlan_mode: 'trunk', all_vlans: true })).toBe(true)
    expect(carriesAllVlans({ vlan_mode: 'access', all_vlans: true })).toBe(false)
    expect(carriesAllVlans({ vlan_mode: 'trunk' })).toBe(false)
  })

  it('расходятся только trunk-порты, у одного из которых стоит «Все VLAN»', () => {
    expect(allVlansDiffer({ vlan_mode: 'trunk', all_vlans: true }, { vlan_mode: 'trunk', all_vlans: false })).toBe(true)
    expect(allVlansDiffer({ vlan_mode: 'trunk', all_vlans: false }, { vlan_mode: 'trunk', all_vlans: true })).toBe(true) // симметрично
    expect(allVlansDiffer({ vlan_mode: 'trunk', all_vlans: true }, { vlan_mode: 'trunk', all_vlans: true })).toBe(false)
    expect(allVlansDiffer({ vlan_mode: 'trunk' }, { vlan_mode: 'trunk', all_vlans: false })).toBe(false) // наборы вручную здесь не сверяются
  })

  it('разные режимы — расхождение уже описано режимом, признак отдельно не сверяется', () => {
    expect(allVlansDiffer({ vlan_mode: 'trunk', all_vlans: true }, { vlan_mode: 'access' })).toBe(false)
    expect(allVlansDiffer({ vlan_mode: 'access' }, { vlan_mode: 'trunk', all_vlans: true })).toBe(false)
  })
})

describe('valueFromSource', () => {
  it('«Все VLAN» источника переносится признаком, набор не нужен', () => {
    expect(valueFromSource({ allVlans: true, numbers: [10, 20] }, options)).toEqual({ value: { allVlans: true, vlanIds: [] }, missing: [] })
  })

  it('набор источника переносится по НОМЕРАМ VLAN; номера, которых у цели нет, не назначаются и возвращаются в missing', () => {
    const target = [vlan('b10', 10), vlan('b30', 30)]
    expect(valueFromSource({ allVlans: false, numbers: [30, 10, 99] }, target)).toEqual({ value: { allVlans: false, vlanIds: ['b10', 'b30'] }, missing: [99] })
  })

  it('пустой набор источника — пустое значение без признака', () => {
    expect(valueFromSource({ allVlans: false, numbers: [] }, options)).toEqual({ value: { allVlans: false, vlanIds: [] }, missing: [] })
  })
})

describe('описание и правка значения', () => {
  it('describeVlanValue: «Все VLAN», номера с диапазонами или «VLAN не выбраны»', () => {
    expect(describeVlanValue({ allVlans: true, vlanIds: [] }, options)).toBe('Все VLAN')
    expect(describeVlanValue({ allVlans: false, vlanIds: ['a10', 'a20', 'a30'] }, options)).toBe('VLAN 10, 20, 30')
    expect(describeVlanValue({ allVlans: false, vlanIds: [] }, options)).toBe('VLAN не выбраны')
  })

  it('«Все VLAN» отмечает в окне выбора все VLAN устройства; ручной выбор признак снимает', () => {
    expect(pickerSelection({ allVlans: true, vlanIds: [] }, options)).toEqual(['a10', 'a20', 'a30'])
    // снять один VLAN при признаке «Все VLAN» — останутся остальные, признака нет
    expect(toggleValueVlan({ allVlans: true, vlanIds: [] }, 'a20', false, options)).toEqual({ allVlans: false, vlanIds: ['a10', 'a30'] })
    expect(toggleValueVlan({ allVlans: false, vlanIds: ['a10'] }, 'a20', true, options)).toEqual({ allVlans: false, vlanIds: ['a10', 'a20'] })
    expect(toggleValueAll(true)).toEqual({ allVlans: true, vlanIds: [] })
    expect(toggleValueAll(false)).toEqual({ allVlans: false, vlanIds: [] })
  })
})
