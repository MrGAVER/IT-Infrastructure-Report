import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionCanvasModal from '../ConnectionCanvasModal.vue'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useConnectionsStore } from '../../stores/connections'
import type { Connection } from '../../api/types'

// jsdom по умолчанию возвращает {top: 0, left: 0, ...} из getBoundingClientRect() для ЛЮБОГО
// элемента (реального layout-движка нет) — координаты схемы (canvasPoint()) в тестах поэтому
// буквально совпадают с clientX/clientY события, без нужды мокать сам rect.
function mouseEvent(type: string, x: number, y: number) {
  return new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true })
}

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    source_interface_id: 'if-a1',
    destination_interface_id: 'if-b1',
    connection_type_id: 'ct-1',
    purpose: null,
    is_active: true,
    description: null,
    source_device_name: 'a',
    source_interface_name: 'eth0',
    destination_device_name: 'b',
    destination_interface_name: 'eth0',
    connection_type_name: 'Медь',
    ...overrides,
  }
}

function choosePort(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.find(`[data-interface-id="${label}"]`)
}

async function chooseDevice(wrapper: ReturnType<typeof mount>, label: string) {
  const select = wrapper.find('.searchable-select')
  await select.find('input').trigger('focus')
  const option = select.findAll('.ss-option').find((o) => o.text() === label)
  if (!option) throw new Error(`Опция "${label}" не найдена`)
  await option.trigger('mousedown')
  await wrapper.find('.canvas-toolbar button.btn-secondary').trigger('click')
}

beforeEach(() => {
  setActivePinia(createPinia())
  // jsdom не реализует elementFromPoint вовсе (нет layout-движка) — определяем как мок, чтобы
  // finishConnectDrag() в компоненте не падал на непроинициализированном методе; конкретное
  // возвращаемое значение переопределяется в тех тестах, где это важно (vi.mocked(...).mockReturnValue).
  document.elementFromPoint = vi.fn(() => null)
  const catalogs = useCatalogsStore()
  catalogs.items['interfaces'] = [
    { id: 'if-a1', physical_device_id: 'dev-a', name: 'eth0' },
    { id: 'if-a2', physical_device_id: 'dev-a', name: 'eth1' },
    { id: 'if-b1', physical_device_id: 'dev-b', name: 'eth0' },
    { id: 'if-c1', physical_device_id: 'dev-c', name: 'eth0' },
  ]
  const devices = useDevicesStore()
  devices.all = [
    { id: 'dev-a', system_name: 'srv-a', serial_number: 'SN-A' } as never,
    { id: 'dev-b', system_name: 'srv-b', serial_number: 'SN-B' } as never,
    { id: 'dev-c', system_name: '', serial_number: 'SN-C' } as never,
  ]
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ConnectionCanvasModal.vue — устройства и порты на схеме', () => {
  it('изначально показывает подсказку добавить устройства, без схемы', () => {
    const wrapper = mount(ConnectionCanvasModal)
    expect(wrapper.find('.canvas-empty').exists()).toBe(true)
    expect(wrapper.find('.canvas-svg').exists()).toBe(false)
  })

  it('добавляет устройство на схему с его портами, повторно предложить его же для добавления нельзя', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    expect(wrapper.find('.canvas-empty').exists()).toBe(false)
    expect(wrapper.find('.device-node .node-title').text()).toBe('srv-a')
    expect(wrapper.findAll('.port-row')).toHaveLength(2) // eth0 + eth1

    // srv-a уже на схеме — не должно быть варианта выбрать его снова.
    const select = wrapper.find('.searchable-select')
    await select.find('input').trigger('focus')
    expect(select.findAll('.ss-option').map((o) => o.text())).not.toContain('srv-a')
  })

  it('устройство без имени показывает серийный номер (deviceLabel — тот же приём, что в ConnectionFormModal.vue)', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'SN-C')
    expect(wrapper.find('.node-title').text()).toBe('SN-C')
  })

  it('устройство без единого порта показывает "Нет портов"', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = []
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    expect(wrapper.find('.node-empty').text()).toBe('Нет портов')
  })

  it('убирает устройство со схемы по кнопке — сама схема пустеет, если оно было единственным', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await wrapper.find('.node-remove').trigger('click')

    expect(wrapper.find('.device-node').exists()).toBe(false)
    expect(wrapper.find('.canvas-empty').exists()).toBe(true)
  })
})

describe('ConnectionCanvasModal.vue — линии существующих подключений', () => {
  it('рисует линию между портами двух устройств, добавленных на схему', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection()]
    connections.loaded = true
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const lines = wrapper.findAll('.connection-line:not(.drag-preview)')
    expect(lines).toHaveLength(1)
    expect(lines[0].classes()).not.toContain('inactive')
  })

  it('неактивное подключение рисуется пунктиром (класс inactive)', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection({ is_active: false })]
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    expect(wrapper.find('.connection-line').classes()).toContain('inactive')
  })

  it('подключение к устройству, не добавленному на схему, линией не показывается', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection()] // dev-b на схему не добавлен
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    expect(wrapper.find('.connection-line').exists()).toBe(false)
  })

  it('клик по линии подключения открывает форму редактирования именно этого подключения', async () => {
    const connections = useConnectionsStore()
    const c = connection()
    connections.all = [c]
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    await wrapper.find('.connection-line').trigger('click')

    const formModal = wrapper.findComponent(ConnectionFormModal)
    expect(formModal.exists()).toBe(true)
    expect(formModal.props('connection')).toEqual(c)
  })
})

describe('ConnectionCanvasModal.vue — перетаскивание порта в порт (фикс п.3.4)', () => {
  it('протяжка от свободного порта к свободному порту другого устройства открывает форму с prefill', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    const targetRowEl = choosePort(wrapper, 'if-b1').element
    vi.mocked(document.elementFromPoint).mockReturnValue(targetRowEl)

    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mousemove', 50, 60))
    window.dispatchEvent(mouseEvent('mouseup', 90, 110))
    await wrapper.vm.$nextTick()

    const formModal = wrapper.findComponent(ConnectionFormModal)
    expect(formModal.exists()).toBe(true)
    expect(formModal.props('connection')).toBeNull()
    expect(formModal.props('prefill')).toEqual({ sourceInterfaceId: 'if-a1', destinationInterfaceId: 'if-b1' })
  })

  it('протяжка рисует временную пунктирную линию, пока кнопка мыши не отпущена', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mousemove', 50, 60))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.connection-line.drag-preview').exists()).toBe(true)

    vi.mocked(document.elementFromPoint).mockReturnValue(null)
    window.dispatchEvent(mouseEvent('mouseup', 50, 60))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.connection-line.drag-preview').exists()).toBe(false)
  })

  it('с уже занятого порта протяжку начать нельзя', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection({ source_interface_id: 'if-a1', destination_interface_id: 'if-b1' })]
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    expect(choosePort(wrapper, 'if-a1').classes()).toContain('occupied')

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mousemove', 50, 60))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.connection-line.drag-preview').exists()).toBe(false)
  })

  it('отпускание на уже занятом порту-получателе показывает ошибку и не открывает форму', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection({ source_interface_id: 'if-c1', destination_interface_id: 'if-b1' })]
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    const targetRowEl = choosePort(wrapper, 'if-b1').element // if-b1 занят подключением выше
    vi.mocked(document.elementFromPoint).mockReturnValue(targetRowEl)

    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mouseup', 90, 110))
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(ConnectionFormModal).exists()).toBe(false)
  })

  it('отпускание на том же порту, с которого начали протяжку, ничего не создаёт', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    const sourceRow = choosePort(wrapper, 'if-a1')
    const sourceEl = sourceRow.find('.port-pin').element
    vi.mocked(document.elementFromPoint).mockReturnValue(sourceRow.element)

    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mouseup', 10, 10))
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(ConnectionFormModal).exists()).toBe(false)
  })

  it('отпускание вне какого-либо порта ничего не создаёт', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    vi.mocked(document.elementFromPoint).mockReturnValue(null)

    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mouseup', 500, 500))
    await wrapper.vm.$nextTick()

    expect(wrapper.findComponent(ConnectionFormModal).exists()).toBe(false)
  })
})

describe('ConnectionCanvasModal.vue — перетаскивание карточки устройства', () => {
  it('перетаскивание за заголовок карточки перемещает её (left/top меняются)', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    const node = wrapper.find('.device-node')
    const before = (node.element as HTMLElement).style.left

    await wrapper.find('.node-header').trigger('mousedown', { clientX: 40, clientY: 40 })
    window.dispatchEvent(mouseEvent('mousemove', 240, 140))
    window.dispatchEvent(mouseEvent('mouseup', 240, 140))
    await wrapper.vm.$nextTick()

    expect((node.element as HTMLElement).style.left).not.toBe(before)
  })

  it('перетаскивание карточки не запускает протяжку соединения (не дёргает elementFromPoint)', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')
    const spy = vi.mocked(document.elementFromPoint)

    await wrapper.find('.node-header').trigger('mousedown', { clientX: 40, clientY: 40 })
    window.dispatchEvent(mouseEvent('mouseup', 240, 140))
    await wrapper.vm.$nextTick()

    expect(spy).not.toHaveBeenCalled()
    expect(wrapper.findComponent(ConnectionFormModal).exists()).toBe(false)
  })
})
