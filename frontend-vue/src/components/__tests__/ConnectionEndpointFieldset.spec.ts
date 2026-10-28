import { describe, expect, it } from 'vitest'
import { mount, type DOMWrapper } from '@vue/test-utils'
import ConnectionEndpointFieldset from '../ConnectionEndpointFieldset.vue'

const deviceOptions = [
  { value: 'dev-1', label: 'alpha' },
  { value: 'dev-2', label: 'beta' },
]
const portOptions = [
  { value: 'if-1', label: 'eth0' },
  { value: 'if-2', label: 'eth1' },
]

type Props = {
  deviceId?: string
  interfaceId?: string
  portOptions?: { value: string; label: string }[]
  hasNoPortsAtAll?: boolean
}

function mountFieldset(props: Props = {}) {
  return mount(ConnectionEndpointFieldset, {
    props: {
      legend: 'Исходное устройство',
      managePortsLabel: 'Управлять портами исходного устройства',
      deviceOptions,
      portOptions: props.portOptions ?? portOptions,
      hasNoPortsAtAll: props.hasNoPortsAtAll ?? false,
      deviceId: props.deviceId ?? '',
      interfaceId: props.interfaceId ?? '',
    },
  })
}

async function chooseOption(select: DOMWrapper<Element>, label: string) {
  await select.find('input').trigger('focus')
  const option = select.findAll('.ss-option').find((o) => o.text() === label)
  if (!option) throw new Error(`Опция "${label}" не найдена среди: ${select.findAll('.ss-option').map((o) => o.text())}`)
  await option.trigger('mousedown')
}

const manageButton = (w: ReturnType<typeof mountFieldset>) => w.find('button.quick-add-btn')
const displayed = (w: DOMWrapper<Element>) => (w.find('input').element as HTMLInputElement).value

describe('ConnectionEndpointFieldset', () => {
  it('показывает подпись стороны и два выбора: устройство и порт', () => {
    const wrapper = mountFieldset()
    expect(wrapper.find('legend').text()).toBe('Исходное устройство')
    expect(wrapper.findAll('.searchable-select')).toHaveLength(2)
    expect(wrapper.text()).toContain('Устройство')
    expect(wrapper.text()).toContain('Порт *')
  })

  it('отображает выбранные устройство и порт', () => {
    const wrapper = mountFieldset({ deviceId: 'dev-2', interfaceId: 'if-1' })
    const [device, port] = wrapper.findAll('.searchable-select')
    expect(displayed(device)).toBe('beta')
    expect(displayed(port)).toBe('eth0')
  })

  it('выбор устройства и порта обновляет значения v-model', async () => {
    const wrapper = mountFieldset({ deviceId: 'dev-1' })
    const [device, port] = wrapper.findAll('.searchable-select')
    await chooseOption(device, 'beta')
    await chooseOption(port, 'eth1')
    expect(wrapper.emitted('update:deviceId')?.at(-1)).toEqual(['dev-2'])
    expect(wrapper.emitted('update:interfaceId')?.at(-1)).toEqual(['if-2'])
  })

  it('пока устройство не выбрано, порт и «Управлять портами» отключены', () => {
    const wrapper = mountFieldset()
    expect(wrapper.findAll('.searchable-select')[1].classes()).toContain('disabled')
    expect((manageButton(wrapper).element as HTMLButtonElement).disabled).toBe(true)
  })

  it('с выбранным устройством кнопка доступна, имеет подпись для скринридера и сообщает об открытии управления портами', async () => {
    const wrapper = mountFieldset({ deviceId: 'dev-1' })
    const button = manageButton(wrapper)
    expect((button.element as HTMLButtonElement).disabled).toBe(false)
    expect(button.attributes('aria-label')).toBe('Управлять портами исходного устройства')
    expect(button.attributes('title')).toBe('Управлять портами устройства')
    await button.trigger('click')
    expect(wrapper.emitted('manage-ports')).toHaveLength(1)
  })

  it('у устройства нет ни одного порта — подсказка «нет ни одного порта»', () => {
    const wrapper = mountFieldset({ deviceId: 'dev-1', portOptions: [], hasNoPortsAtAll: true })
    expect(wrapper.find('.hint-small').text()).toContain('У устройства пока нет ни одного порта')
  })

  it('все порты заняты (опций нет, но порты у устройства есть) — подсказка «нет свободных портов»', () => {
    const wrapper = mountFieldset({ deviceId: 'dev-1', portOptions: [] })
    const hints = wrapper.findAll('.hint-small')
    expect(hints).toHaveLength(1)
    expect(hints[0].text()).toContain('Нет свободных портов — все заняты активными подключениями')
  })

  it('«нет портов вообще» важнее «все заняты»: показывается только одна подсказка', () => {
    const wrapper = mountFieldset({ deviceId: 'dev-1', portOptions: [], hasNoPortsAtAll: true })
    expect(wrapper.findAll('.hint-small')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Нет свободных портов')
  })

  it('есть свободные порты — подсказок нет', () => {
    expect(mountFieldset({ deviceId: 'dev-1' }).find('.hint-small').exists()).toBe(false)
  })

  it('устройство не выбрано — подсказки «все заняты» нет, хотя опций портов нет', () => {
    expect(mountFieldset({ portOptions: [] }).find('.hint-small').exists()).toBe(false)
  })
})
