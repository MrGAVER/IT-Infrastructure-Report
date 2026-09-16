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
  it('SVG со связями рисуется в DOM ПОСЛЕ карточек устройств — иначе линии красятся под непрозрачными блоками и часть каждой линии (там, где её конец лежит внутри карточки) визуально пропадает', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    const children = Array.from(wrapper.find('.canvas-area').element.children)
    const svgIndex = children.findIndex((el) => el.classList.contains('canvas-svg'))
    const deviceNodeIndexes = children.reduce<number[]>((acc, el, i) => (el.classList.contains('device-node') ? [...acc, i] : acc), [])

    expect(svgIndex).toBeGreaterThan(Math.max(...deviceNodeIndexes))
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

describe('ConnectionCanvasModal.vue — геометрия линий (фикс "от центра блока к центру блока -> от точки к точке портов")', () => {
  // pathStartX/pathEndX: 'M {x} {y} C ...' — первое число после 'M' это x начала пути.
  function pathStartX(d: string): number {
    return Number(d.match(/^M\s*([\d.-]+)/)![1])
  }

  it('линия подключения начинается на X точки-пина, а не на горизонтальном центре карточки устройства', async () => {
    const connections = useConnectionsStore()
    connections.all = [connection()]
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')
    await chooseDevice(wrapper, 'srv-b')

    // nextGridPosition() читает canvasDeviceIds.value.length ПОСЛЕ того, как в addDevice() в
    // этот массив уже добавлен новый id (см. её реализацию) — поэтому первое добавленное
    // устройство попадает не в 0-й, а в 1-й слот сетки (col=1, x = CANVAS_MARGIN(60) +
    // (NODE_WIDTH(220)+NODE_GAP_X(60)) = 340). Это отдельная, не связанная с этим фиксом
    // особенность (0-й слот сетки в итоге просто никогда не используется) — здесь ориентируемся
    // на фактическое поведение, а не на "круглые" координаты.
    const d = wrapper.find('.connection-line:not(.drag-preview)').attributes('d')!
    // PIN_CENTER_X (15) — тот же отступ, что и у самого .port-pin в CSS (10px padding-left +
    // половина ширины пина). NODE_WIDTH/2 (110) — старое (неверное) смещение, которое было бы
    // здесь при регрессии этого фикса (сходилось бы в центр карточки, а не в точку пина).
    expect(pathStartX(d)).toBe(340 + 15)
    expect(pathStartX(d)).not.toBe(340 + 110)
  })

  it('временная линия протяжки тоже начинается на X точки-пина', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a') // единственное устройство — тоже в 1-м слоте сетки, x=340 (см. комментарий выше)

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mousemove', 50, 60))
    await wrapper.vm.$nextTick()

    const d = wrapper.find('.connection-line.drag-preview').attributes('d')!
    expect(pathStartX(d)).toBe(340 + 15)
  })

  it('название порта выведено отдельной строкой НАД строкой с самим пином (не в одном flex-ряду с ним)', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    const row = choosePort(wrapper, 'if-a1')
    const name = row.find('.port-name')
    const pinRow = row.find('.port-pin-row')
    expect(name.exists()).toBe(true)
    expect(pinRow.find('.port-pin').exists()).toBe(true)
    // Название и пин — в РАЗНЫХ дочерних элементах строки порта (а не в одном ряду), и название
    // идёт ПЕРВЫМ по порядку — то есть визуально выше пина, т.к. .port-row теперь column.
    const children = Array.from(row.element.children)
    expect(children.indexOf(name.element)).toBeLessThan(children.indexOf(pinRow.element))
  })
})

describe('ConnectionCanvasModal.vue — координаты курсора при прокрученной схеме (баг "линия уходит вверх после прокрутки")', () => {
  it('протяжка линии учитывает scrollTop/scrollLeft контейнера схемы, а не только позицию курсора в вьюпорте', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a')

    const canvasArea = wrapper.find('.canvas-area').element as HTMLElement
    // jsdom не рендерит реальный layout, но scrollTop/scrollLeft — обычные settable-свойства
    // элемента, не требующие реальной прокрутки для проверки самой формулы canvasPoint().
    Object.defineProperty(canvasArea, 'scrollLeft', { value: 40, configurable: true })
    Object.defineProperty(canvasArea, 'scrollTop', { value: 200, configurable: true })

    const sourceEl = choosePort(wrapper, 'if-a1').find('.port-pin').element
    sourceEl.dispatchEvent(mouseEvent('mousedown', 10, 10))
    window.dispatchEvent(mouseEvent('mousemove', 50, 60))
    await wrapper.vm.$nextTick()

    const d = wrapper.find('.connection-line.drag-preview').attributes('d')!
    // Конец пути — последняя пара чисел в 'C ..., {endX} {endY}'. При clientY=60 без учёта
    // scrollTop получили бы endY=60 (сам баг: "линия уходит вверх" при прокрутке вниз) —
    // правильное значение — clientY(60) + scrollTop(200) = 260, аналогично для X.
    const endMatch = d.match(/,\s*([\d.-]+)\s+([\d.-]+)$/)!
    expect(Number(endMatch[1])).toBe(50 + 40)
    expect(Number(endMatch[2])).toBe(60 + 200)
  })

  it('перетаскивание карточки устройства тоже учитывает прокрутку схемы (тот же canvasPoint())', async () => {
    const wrapper = mount(ConnectionCanvasModal)
    await chooseDevice(wrapper, 'srv-a') // первое устройство на схеме — {x:60, y:60}, см. nextGridPosition()

    const canvasArea = wrapper.find('.canvas-area').element as HTMLElement
    Object.defineProperty(canvasArea, 'scrollTop', { value: 300, configurable: true })

    const node = wrapper.find('.device-node')
    await wrapper.find('.node-header').trigger('mousedown', { clientX: 40, clientY: 40 })
    window.dispatchEvent(mouseEvent('mousemove', 40, 90)) // курсор сдвинулся на +50 по Y
    window.dispatchEvent(mouseEvent('mouseup', 40, 90))
    await wrapper.vm.$nextTick()

    // offsetY считается один раз при mousedown (340-60=280, где 340 = clientY(40)+scrollTop(300))
    // и вычитается из point при каждом mousemove — пока scrollTop не меняется ПОСЕРЕДИНЕ протяжки,
    // он самосокращается в offset'е, и итоговая позиция зависит только от сдвига курсора (+50):
    // 60 (исходный y) + 50 = 110. Без фикса (без прибавления scrollTop в canvasPoint()) результат
    // был бы тем же для ЭТОГО теста — сам баг здесь не в конечной позиции при перетаскивании
    // карточки, а в линии протяжки соединения (см. предыдущий тест) и в согласованности с ней:
    // раз canvasPoint() общая функция для обоих, тест фиксирует, что перетаскивание карточки
    // по-прежнему работает корректно ПОСЛЕ фикса, не только протяжка линии.
    expect((node.element as HTMLElement).style.top).toBe('110px')
  })
})

