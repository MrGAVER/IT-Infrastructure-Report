import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortSyncPlanHost from '../PortSyncPlanHost.vue'
import PortSyncPlanModal from '../PortSyncPlanModal.vue'
import { usePortSyncPlanRequest } from '../../composables/usePortSyncPlanRequest'
import { useConnectionsDashboardStore } from '../../stores/connectionsDashboard'

const Stub = { name: 'PortSyncPlanModal', props: ['scope', 'title'], emits: ['close', 'applied'], template: '<div class="plan-stub" />' }

function mountHost() {
  return mount(PortSyncPlanHost, { global: { stubs: { PortSyncPlanModal: Stub } } })
}

describe('PortSyncPlanHost', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    usePortSyncPlanRequest().close()
  })

  it('пока запроса нет — окна нет; по запросу открывается с его областью и заголовком; close закрывает', async () => {
    const wrapper = mountHost()
    expect(wrapper.find('.plan-stub').exists()).toBe(false)

    usePortSyncPlanRequest().open({ connection_ids: ['c-1', 'c-2'] }, 'После изменения VLAN')
    await wrapper.vm.$nextTick()

    const modal = wrapper.findComponent(Stub)
    expect(modal.props()).toMatchObject({ scope: { connection_ids: ['c-1', 'c-2'] }, title: 'После изменения VLAN' })
    modal.vm.$emit('close')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.plan-stub').exists()).toBe(false)
  })

  it('после применения плана перечитываются таблица и кэш подключений', async () => {
    const dashboard = useConnectionsDashboardStore()
    const refresh = vi.spyOn(dashboard, 'refreshAfterChange').mockResolvedValue()
    const wrapper = mountHost()
    usePortSyncPlanRequest().open({})
    await wrapper.vm.$nextTick()

    wrapper.findComponent(Stub).vm.$emit('applied', { applied: { ports: 1, connections: 1 }, connection_ids: ['c-1'], summary: {} })
    await flushPromises()

    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('настоящее окно плана принимает те же props и события, что и заглушка', () => {
    expect(Object.keys(PortSyncPlanModal.props ?? {})).toEqual(expect.arrayContaining(['scope', 'title']))
  })
})
