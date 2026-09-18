import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramDeviceNode from '../DiagramDeviceNode.vue'
import type { DiagramDeviceNode as DeviceNodeData } from '../../../api/diagrams'
import { makeNodeProps } from './nodeTestHelpers'

// Handle из @vue-flow/core требует полноценный контекст родителя <VueFlow> (внутренний стор
// размеров/позиций), а сам по себе не несёт данных, которые эти тесты проверяют (форма/цвет/
// засечки/подписи) — стаб позволяет монтировать компонент узла напрямую по props, не поднимая
// ResizeObserver/getBoundingClientRect-заглушки ради полноценного канваса (это отдельно
// проверяется на уровне DiagramView.vue, где Handle учитывается по факту наличия/id).
const stubs = { Handle: true }

const baseDevice: DeviceNodeData = {
  id: 'dev-1',
  type: 'device',
  label: 'sw-01',
  serial_number: 'SN-1',
  system_name: 'sw-01',
  category_id: null,
  manufacturer: null,
  model: null,
  ip_addresses: [],
  icon: { mode: 'generated', shape: 'server', color: '#4f7cff', manufacturer_label: '', model_label: '' },
  x: 0,
  y: 0,
}

function mountNode(data: DeviceNodeData, selected = false) {
  return mount(DiagramDeviceNode, {
    props: makeNodeProps(data, { selected }),
    global: { stubs },
  })
}

describe('DiagramDeviceNode.vue', () => {
  it('без данных port_ticks не рисует засечки, показывает подпись устройства', () => {
    const wrapper = mountNode(baseDevice)
    expect(wrapper.text()).toContain('sw-01')
    expect(wrapper.find('.port-ticks').exists()).toBe(false)
  })

  it('засечки теперь рисуются для ЛЮБОЙ формы со сгенерированным значком, не только switch', () => {
    // Регрессия: раньше видимость засечек была жёстко завязана на shape === 'switch', из-за чего
    // сервер/файрвол с несколькими интерфейсами анкерил все свои связи в одну и ту же точку узла.
    const serverWithPorts: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape: 'server', color: '#4f7cff', port_ticks: 2, manufacturer_label: '', model_label: '' },
    }
    const wrapper = mountNode(serverWithPorts)
    expect(wrapper.findAll('.port-tick')).toHaveLength(2)
  })

  it('для shape=switch рисует засечки портов по числу port_ticks и бейдж overflow', () => {
    const switchDevice: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', port_ticks: 5, port_overflow: 12, manufacturer_label: 'Cisco', model_label: 'C2960' },
    }
    const wrapper = mountNode(switchDevice)
    expect(wrapper.findAll('.port-tick')).toHaveLength(5)
    expect(wrapper.text()).toContain('+12')
    expect(wrapper.text()).toContain('Cisco')
  })

  it('иконка mode=custom санитизирует и встраивает svg_markup (код-ревью п.3.1)', () => {
    // Полноценный <svg>-документ — реалистичная форма DiagramIcon.svg_markup (не голый
    // фрагмент): sanitizeSvg (utils/sanitizeSvg.ts) требует SVG-контекст, иначе DOMPurify
    // не распознаёт дочерние элементы как принадлежащие пространству имён SVG и отбрасывает их.
    const customDevice: DeviceNodeData = { ...baseDevice, icon: { mode: 'custom', svg_markup: '<svg><circle r="4" class="mark"/></svg>' } }
    const wrapper = mountNode(customDevice)
    expect(wrapper.find('.custom-icon .mark').exists()).toBe(true)
  })

  it('иконка mode=custom вырезает исполняемое содержимое SVG (код-ревью п.3.1, XSS)', () => {
    const maliciousDevice: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'custom', svg_markup: '<svg onload="alert(1)"><script>alert(1)</script><circle r="4" class="mark"/></svg>' },
    }
    const wrapper = mountNode(maliciousDevice)
    expect(wrapper.find('.custom-icon script').exists()).toBe(false)
    expect(wrapper.find('.custom-icon svg').attributes('onload')).toBeUndefined()
    expect(wrapper.find('.custom-icon .mark').exists()).toBe(true) // безопасное содержимое сохраняется
  })

  it('порог в 32 засечки не превышается даже при большем port_ticks в данных', () => {
    const overflowingDevice: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', port_ticks: 40, manufacturer_label: '', model_label: '' },
    }
    const wrapper = mountNode(overflowingDevice)
    expect(wrapper.findAll('.port-tick')).toHaveLength(32)
  })

  it('выделенный узел получает класс selected', () => {
    const wrapper = mountNode(baseDevice, true)
    expect(wrapper.find('.diagram-device-node').classes()).toContain('selected')
  })

  it('показывает серийный номер и IP на самом значке (не только в панели деталей по клику)', () => {
    const deviceWithIp: DeviceNodeData = {
      ...baseDevice,
      serial_number: 'SN-777',
      ip_addresses: [
        { address: '10.0.0.5', purpose: null, is_management: false },
        { address: '10.0.0.1', purpose: 'management', is_management: true },
      ],
    }
    const wrapper = mountNode(deviceWithIp)
    // management-адрес показан, а не первый в списке
    expect(wrapper.find('.identity-label').text()).toBe('SN-777 · 10.0.0.1')
  })

  it('без IP-адресов показывает только серийный номер, без хвостового разделителя', () => {
    const wrapper = mountNode({ ...baseDevice, serial_number: 'SN-42', ip_addresses: [] })
    expect(wrapper.find('.identity-label').text()).toBe('SN-42')
  })

  it('без management-адреса берёт первый IP из списка', () => {
    const device: DeviceNodeData = {
      ...baseDevice,
      serial_number: 'SN-1',
      ip_addresses: [
        { address: '192.168.1.10', purpose: null, is_management: false },
        { address: '192.168.1.11', purpose: null, is_management: false },
      ],
    }
    const wrapper = mountNode(device)
    expect(wrapper.find('.identity-label').text()).toBe('SN-1 · 192.168.1.10')
  })

  it.each(['switch_l2', 'switch_l3', 'router'] as const)('рендерит новый значок формы %s без ошибок', (shape) => {
    const device: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape, color: '#2fa86a', manufacturer_label: '', model_label: '' },
    }
    const wrapper = mountNode(device)
    const path = wrapper.find('.shape-glyph path').attributes('d')
    expect(path).toBeTruthy()
    // switch_l2/switch_l3/router — три РАЗНЫЕ формы, ни одна не должна молча съезжать на
    // generic-заглушку (ромб 'M6 1 11 6 6 11 1 6z') из-за отсутствия в SHAPE_GLYPHS.
    expect(path).not.toBe('M6 1 11 6 6 11 1 6z')
  })

  it('switch_l2 и switch_l3 — разные значки (различимы визуально по уровню коммутации)', () => {
    const l2 = mountNode({ ...baseDevice, icon: { mode: 'generated', shape: 'switch_l2', color: '#2fa86a', manufacturer_label: '', model_label: '' } })
    const l3 = mountNode({ ...baseDevice, icon: { mode: 'generated', shape: 'switch_l3', color: '#2fa86a', manufacturer_label: '', model_label: '' } })
    expect(l2.find('.shape-glyph path').attributes('d')).not.toBe(l3.find('.shape-glyph path').attributes('d'))
  })
})
