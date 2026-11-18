import { describe, it, expect } from 'vitest'
import type { Device, DeviceStack } from '../../api/types'
import { buildStackSummaries, splitIps, stackSearchTexts, stackStats } from '../stackSummary'
import type { StackLabelResolvers } from '../stackSummary'

function device(overrides: Partial<Device>): Device {
  return {
    id: 'id-' + Math.random().toString(36).slice(2),
    device_type_id: 'dt-1',
    manufacturer_id: null,
    model_id: null,
    serial_number: 'SN-0000',
    system_name: null,
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: false,
    building_id: null,
    room_id: null,
    rack_id: null,
    rack_position: null,
    description: null,
    diagram_icon_id: null,
    oac_certificate_number: null,
    oac_certificate_registry_date: null,
    stack_id: null,
    stack_name: null,
    stack_position: null,
    management_interface: '',
    management_ips: '',
    interface_count: 0,
    embedded_os_name: '',
    embedded_os_version: '',
    vlan_summary: '',
    ...overrides,
  }
}

// Подписи каталогов в тестах берутся прямо из полей description (модель) и rack_position (место) — логике сводки
// важно только, что подписи уникализируются и попадают в строки, а не откуда их достал вызывающий.
const labels: StackLabelResolvers = {
  model: (d) => d.description ?? '',
  place: (d) => d.rack_position ?? '',
}

const core: DeviceStack = { id: 's-core', name: 'Стек ядра', description: 'Два коммутатора ядра' }
const empty: DeviceStack = { id: 's-empty', name: 'Пустой стек', description: null }

describe('splitIps', () => {
  it('делит строку из management_ips по «;», запятым и пробелам', () => {
    expect(splitIps('10.0.0.1; 10.0.0.2, 10.0.0.3')).toEqual(['10.0.0.1', '10.0.0.2', '10.0.0.3'])
  })
  it('пустое значение и null дают пустой список', () => {
    expect(splitIps('')).toEqual([])
    expect(splitIps(null)).toEqual([])
  })
})

describe('buildStackSummaries', () => {
  it('собирает состав стека по stack_id, участники идут по позиции, без позиции — в конце', () => {
    const rows = buildStackSummaries(
      [core],
      [
        device({ id: 'c', system_name: 'sw-c', stack_id: 's-core', stack_position: null }),
        device({ id: 'b', system_name: 'sw-b', stack_id: 's-core', stack_position: 2 }),
        device({ id: 'a', system_name: 'sw-a', stack_id: 's-core', stack_position: 1 }),
        device({ id: 'x', system_name: 'вне стека' }),
      ],
      labels,
    )

    expect(rows).toHaveLength(1)
    expect(rows[0].members.map((m) => m.name)).toEqual(['sw-a', 'sw-b', 'sw-c'])
  })

  it('имя участника — системное имя, а без него серийный номер', () => {
    const [row] = buildStackSummaries([core], [device({ serial_number: 'SN-77', stack_id: 's-core', stack_position: 1 })], labels)
    expect(row.members[0].name).toBe('SN-77')
  })

  it('стек без устройств остаётся в списке — состояние «empty», пустые модели, IP и места', () => {
    const [row] = buildStackSummaries([empty], [device({ stack_id: 's-core' })], labels)
    expect(row.members).toEqual([])
    expect(row.siemState).toBe('empty')
    expect([row.models, row.places, row.ips]).toEqual([[], [], []])
  })

  it('модели, места и IP по участникам — без повторов', () => {
    const [row] = buildStackSummaries(
      [core],
      [
        device({ stack_id: 's-core', stack_position: 1, description: 'Cisco C9300', rack_position: 'Серверная', management_ips: '10.0.0.1; 10.0.1.1' }),
        device({ stack_id: 's-core', stack_position: 2, description: 'Cisco C9300', rack_position: 'Серверная', management_ips: '10.0.0.2; 10.0.1.1' }),
      ],
      labels,
    )
    expect(row.models).toEqual(['Cisco C9300'])
    expect(row.places).toEqual(['Серверная'])
    expect(row.ips).toEqual(['10.0.0.1', '10.0.1.1', '10.0.0.2'])
  })

  it.each([
    [[false, false], 'none', 0],
    [[true, false], 'partial', 1],
    [[true, true], 'all', 2],
  ])('покрытие SIEM %j → %s', (siem, expected, covered) => {
    const devices = (siem as boolean[]).map((on, i) => device({ stack_id: 's-core', stack_position: i + 1, siem_enabled: on }))
    const [row] = buildStackSummaries([core], devices, labels)
    expect(row.siemState).toBe(expected)
    expect(row.siemCovered).toBe(covered)
  })

  it('стеки сортируются по названию естественным порядком («Стек 2» раньше «Стек 10»)', () => {
    const rows = buildStackSummaries(
      [
        { id: '10', name: 'Стек 10', description: null },
        { id: '2', name: 'Стек 2', description: null },
      ],
      [],
      labels,
    )
    expect(rows.map((r) => r.stack.name)).toEqual(['Стек 2', 'Стек 10'])
  })
})

describe('stackSearchTexts / stackStats', () => {
  const rows = buildStackSummaries(
    [core, empty],
    [
      device({
        system_name: 'sw-a',
        serial_number: 'SN-A',
        stack_id: 's-core',
        stack_position: 1,
        siem_enabled: true,
        description: 'Cisco C9300',
        management_ips: '10.0.0.1',
      }),
      device({
        system_name: 'sw-b',
        serial_number: 'SN-B',
        stack_id: 's-core',
        stack_position: 2,
        siem_enabled: false,
        description: 'Cisco C9300',
        management_ips: '10.0.0.2',
      }),
    ],
    labels,
  )

  it('в тексты поиска входят название, описание, имена и серийные номера участников, модели и IP', () => {
    const texts = stackSearchTexts(rows[1]) // «Стек ядра» (сортировка: «Пустой стек» идёт первым)
    expect(rows[1].stack.id).toBe('s-core')
    expect(texts).toEqual(expect.arrayContaining(['Стек ядра', 'Два коммутатора ядра', 'sw-a', 'SN-B', 'Cisco C9300', '10.0.0.2']))
  })

  it('статистика: стеки, устройства в стеках, пустые стеки и стеки с неполным SIEM', () => {
    expect(stackStats(rows)).toEqual({ stacks: 2, devices: 2, empty: 1, siemIncomplete: 1 })
  })
})
