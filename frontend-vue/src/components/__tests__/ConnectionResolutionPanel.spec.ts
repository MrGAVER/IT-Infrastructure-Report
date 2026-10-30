import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConnectionResolutionPanel from '../ConnectionResolutionPanel.vue'
import type { ConfigView } from '../../utils/connectionPortView'

function view(diff: ConfigView['diff'], patch: { srcMode?: 'access' | 'trunk' | null; dstMode?: 'access' | 'trunk' | null } = {}): ConfigView {
  return {
    status: 'mismatch',
    diff,
    source: { id: 'if-a', name: 'Gi0/1', role: 'management', mode: patch.srcMode === undefined ? 'trunk' : patch.srcMode, vlans: [10, 20] },
    destination: { id: 'if-b', name: 'eth0', role: 'data', mode: patch.dstMode === undefined ? 'access' : patch.dstMode, vlans: [10] },
  }
}

const mountPanel = (mismatch: ConfigView) => mount(ConnectionResolutionPanel, { props: { mismatch } })
const actions = (w: ReturnType<typeof mountPanel>) => w.findAll('[data-resolution]').map((b) => b.attributes('data-resolution'))

describe('ConnectionResolutionPanel', () => {
  it('сообщение называет различающиеся грани и описывает обе стороны', () => {
    const text = mountPanel(view(['role', 'mode', 'vlans']))
      .find('.warning-text')
      .text()
    expect(text).toContain('Конфигурации портов различаются (роль, режим, VLAN)')
    expect(text).toContain('«Gi0/1» — Управление активами · trunk · VLAN 10, 20')
    expect(text).toContain('«eth0» — Передача данных · access · VLAN 10')
    expect(text).toContain('Что сделать перед сохранением?')
  })

  it('роль различается: можно выровнять роль любого из портов; режимов и подсказки про VLAN нет', () => {
    const wrapper = mountPanel(view(['role']))
    expect(actions(wrapper)).toEqual(['keep-source', 'keep-destination', 'approve', 'back'])
    expect(wrapper.find('[data-hint]').exists()).toBe(false)
  })

  it('подписи кнопок роли называют порты', () => {
    const wrapper = mountPanel(view(['role']))
    expect(wrapper.find('[data-resolution="keep-source"]').text()).toBe('Порту «eth0» задать роль как у «Gi0/1»')
    expect(wrapper.find('[data-resolution="keep-destination"]').text()).toBe('Порту «Gi0/1» задать роль как у «eth0»')
  })

  it('режим различается и известен у обоих портов: кнопки режима с текущим режимом победителя и подсказка про каскад', () => {
    const wrapper = mountPanel(view(['mode']))
    expect(actions(wrapper)).toEqual(['mode-keep-source', 'mode-keep-destination', 'approve', 'back'])
    expect(wrapper.find('[data-resolution="mode-keep-source"]').text()).toBe('Порту «eth0» задать режим как у «Gi0/1» (trunk)')
    expect(wrapper.find('[data-resolution="mode-keep-destination"]').text()).toBe('Порту «Gi0/1» задать режим как у «eth0» (access)')
    expect(wrapper.find('[data-hint="mode-cascade"]').text()).toContain('перед применением покажем список последствий')
  })

  it('режим различается, но неизвестен (нет ответа сервера): выровнять режим нельзя', () => {
    const wrapper = mountPanel(view(['mode'], { srcMode: null }))
    expect(actions(wrapper)).toEqual(['approve', 'back'])
    expect(wrapper.find('[data-hint="mode-cascade"]').exists()).toBe(false)
  })

  it('VLAN различаются: подсказка отправляет в окно портов, а кнопок выравнивания VLAN нет', () => {
    const wrapper = mountPanel(view(['vlans']))
    expect(actions(wrapper)).toEqual(['approve', 'back'])
    expect(wrapper.find('[data-hint="port-setup"]').text()).toContain('VLAN меняются в окне портов устройства')
  })

  it('все грани сразу: роль, режим, подсказки и обе постоянные кнопки — в порядке интерфейса', () => {
    expect(actions(mountPanel(view(['role', 'mode', 'vlans'])))).toEqual([
      'keep-source',
      'keep-destination',
      'mode-keep-source',
      'mode-keep-destination',
      'approve',
      'back',
    ])
  })

  it.each(['keep-source', 'keep-destination', 'mode-keep-source', 'mode-keep-destination', 'approve'] as const)(
    'кнопка «%s» отправляет решение',
    async (resolution) => {
      const wrapper = mountPanel(view(['role', 'mode']))
      await wrapper.find(`[data-resolution="${resolution}"]`).trigger('click')
      expect(wrapper.emitted('resolve')).toEqual([[resolution]])
      expect(wrapper.emitted('back')).toBeUndefined()
    },
  )

  it('«Вернуться к правке» отправляет back, а не решение', async () => {
    const wrapper = mountPanel(view(['role']))
    await wrapper.find('[data-resolution="back"]').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
    expect(wrapper.emitted('resolve')).toBeUndefined()
  })

  it('это окно оповещения с подписью для скринридера', () => {
    const root = mountPanel(view(['role'])).find('.resolution')
    expect(root.attributes('role')).toBe('alertdialog')
    expect(root.attributes('aria-label')).toBe('Расхождение конфигурации портов')
  })

  it('пока панель показана, набор кнопок следует за изменением расхождения (пользователь сменил порт)', async () => {
    const wrapper = mountPanel(view(['role']))
    expect(actions(wrapper)).toContain('keep-source')
    await wrapper.setProps({ mismatch: view(['mode', 'vlans']) })
    expect(actions(wrapper)).toEqual(['mode-keep-source', 'mode-keep-destination', 'approve', 'back'])
    expect(wrapper.find('[data-hint="port-setup"]').exists()).toBe(true)
    expect(wrapper.find('.warning-text').text()).toContain('(режим, VLAN)')
  })
})
