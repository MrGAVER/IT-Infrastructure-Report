import { describe, expect, it } from 'vitest'
import { iface, preview, previewSide } from '../../composables/__tests__/connectionFormTestkit'
import { buildConfigView, canAlignMode, sideLabel, viewDiffers, type ConfigView } from '../connectionPortView'

const a = iface('if-a', 'dev-1', { is_management: true })
const b = iface('if-b', 'dev-2', { is_data_transfer: true })

describe('buildConfigView', () => {
  it('пара не выбрана — null', () => {
    expect(buildConfigView(null, b, null)).toBeNull()
    expect(buildConfigView(a, null, null)).toBeNull()
  })

  it('ответ сервера, относящийся к выбранной паре, определяет статус, различия, роль, режим и VLAN', () => {
    const view = buildConfigView(
      a,
      b,
      preview(
        previewSide('if-a', { role: 'management', mode: 'trunk', vlans: [10, 20] }),
        previewSide('if-b', { role: 'data', mode: 'access', vlans: [] }),
        'mismatch',
        ['role', 'mode', 'vlans'],
      ),
    )
    expect(view).toEqual({
      status: 'mismatch',
      diff: ['role', 'mode', 'vlans'],
      source: { id: 'if-a', name: 'if-a', role: 'management', mode: 'trunk', vlans: [10, 20] },
      destination: { id: 'if-b', name: 'if-b', role: 'data', mode: 'access', vlans: [] },
    })
  })

  it('устаревший ответ (выбран другой порт) игнорируется — сверка ролей по каталогу', () => {
    const stale = preview(previewSide('if-old'), previewSide('if-b'), 'approved', ['mode'])
    const view = buildConfigView(a, b, stale)!
    expect(view.status).toBe('mismatch')
    expect(view.diff).toEqual(['role'])
    expect(view.source.mode).toBeNull()
    expect(view.source.vlans).toBeNull()
  })

  it('ответ для другого порта назначения тоже считается устаревшим', () => {
    const stale = preview(previewSide('if-a'), previewSide('if-other'), 'approved', ['mode'])
    expect(buildConfigView(a, b, stale)!.diff).toEqual(['role'])
  })

  it('без ответа и с одинаковыми ролями — ok без различий; режим и VLAN неизвестны', () => {
    const same = iface('if-c', 'dev-2', { is_management: true })
    const view = buildConfigView(a, same, null)!
    expect(view.status).toBe('ok')
    expect(view.diff).toEqual([])
    expect(view.source).toEqual({ id: 'if-a', name: 'if-a', role: 'management', mode: null, vlans: null })
    expect(view.destination.role).toBe('management')
  })

  it('без ответа и с разными ролями — расхождение по роли, роли берутся из флагов портов', () => {
    const view = buildConfigView(a, b, null)!
    expect(view.status).toBe('mismatch')
    expect(view.diff).toEqual(['role'])
    expect(view.source.role).toBe('management')
    expect(view.destination.role).toBe('data')
  })
})

describe('sideLabel', () => {
  it('роль · режим · VLAN', () => {
    expect(sideLabel({ id: 'x', name: 'x', role: 'management_data', mode: 'trunk', vlans: [10, 11, 12, 20] })).toBe(
      'Передача данных и управление активами · trunk · VLAN 10–12, 20',
    )
  })

  it('режим и VLAN неизвестны — только роль', () => {
    expect(sideLabel({ id: 'x', name: 'x', role: 'data', mode: null, vlans: null })).toBe('Передача данных')
  })

  it('пустой набор VLAN показывается как «VLAN нет»', () => {
    expect(sideLabel({ id: 'x', name: 'x', role: 'none', mode: 'access', vlans: [] })).toBe('не задано · access · VLAN нет')
  })
})

describe('viewDiffers / canAlignMode', () => {
  const view = (diff: ConfigView['diff'], srcMode: 'access' | 'trunk' | null = 'access', dstMode: 'access' | 'trunk' | null = 'trunk'): ConfigView => ({
    status: 'mismatch',
    diff,
    source: { id: 's', name: 's', role: 'data', mode: srcMode, vlans: null },
    destination: { id: 'd', name: 'd', role: 'data', mode: dstMode, vlans: null },
  })

  it('viewDiffers: есть ли грань в списке различий; для null — false', () => {
    expect(viewDiffers(view(['role', 'vlans']), 'role')).toBe(true)
    expect(viewDiffers(view(['role']), 'mode')).toBe(false)
    expect(viewDiffers(null, 'role')).toBe(false)
  })

  it('canAlignMode: режим различается и известен у обоих портов', () => {
    expect(canAlignMode(view(['mode']))).toBe(true)
  })

  it('canAlignMode: режим не различается — нельзя', () => {
    expect(canAlignMode(view(['role', 'vlans']))).toBe(false)
  })

  it('canAlignMode: режим неизвестен хотя бы у одного порта (нет ответа сервера) — нельзя', () => {
    expect(canAlignMode(view(['mode'], null, 'trunk'))).toBe(false)
    expect(canAlignMode(view(['mode'], 'access', null))).toBe(false)
  })

  it('canAlignMode: пары нет — нельзя', () => {
    expect(canAlignMode(null)).toBe(false)
  })
})
