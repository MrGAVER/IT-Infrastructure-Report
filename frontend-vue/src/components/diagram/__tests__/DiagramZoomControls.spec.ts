// UI-02 (ревью 2.158.0): кнопки масштаба диаграммы подписаны по-русски, гаснут на пределах масштаба и вызывают методы Vue Flow.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

const flow = vi.hoisted(() => ({ zoomIn: vi.fn(), zoomOut: vi.fn(), fitView: vi.fn() }))
const state = vi.hoisted(() => ({ zoom: null as null | { value: number } }))

vi.mock('@vue-flow/core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@vue-flow/core')>()),
  useVueFlow: () => ({
    ...flow,
    viewport: { value: { x: 0, y: 0, zoom: state.zoom!.value } },
    minZoom: ref(0.1),
    maxZoom: ref(2.5),
  }),
}))

import DiagramZoomControls from '../DiagramZoomControls.vue'

function mountControls(zoom: number) {
  state.zoom = { value: zoom }
  return mount(DiagramZoomControls, { global: { stubs: { Panel: { template: '<div v-bind="$attrs"><slot /></div>' } } } })
}

const button = (wrapper: ReturnType<typeof mountControls>, name: string) => wrapper.get(`button[aria-label="${name}"]`)

beforeEach(() => {
  flow.zoomIn.mockReset()
  flow.zoomOut.mockReset()
  flow.fitView.mockReset()
})

describe('UI-02: DiagramZoomControls', () => {
  it('три кнопки с русскими aria-label и title, группа подписана', () => {
    const wrapper = mountControls(1)
    expect(wrapper.get('[role="group"]').attributes('aria-label')).toBe('Масштаб диаграммы')
    for (const name of ['Увеличить масштаб', 'Уменьшить масштаб', 'Показать всю диаграмму']) {
      expect(button(wrapper, name).attributes('title')).toBe(name)
    }
  })

  it('кнопки вызывают zoomIn, zoomOut и fitView с теми же полями, что и начальное вписывание', async () => {
    const wrapper = mountControls(1)
    await button(wrapper, 'Увеличить масштаб').trigger('click')
    await button(wrapper, 'Уменьшить масштаб').trigger('click')
    await button(wrapper, 'Показать всю диаграмму').trigger('click')
    expect(flow.zoomIn).toHaveBeenCalledTimes(1)
    expect(flow.zoomOut).toHaveBeenCalledTimes(1)
    expect(flow.fitView).toHaveBeenCalledWith(expect.objectContaining({ padding: 0.1, maxZoom: 1 }))
  })

  it('на пределе масштаба соответствующая кнопка заблокирована, с допуском на дробное значение', () => {
    expect(button(mountControls(2.4995), 'Увеличить масштаб').attributes('disabled')).toBeDefined()
    expect(button(mountControls(2.4995), 'Уменьшить масштаб').attributes('disabled')).toBeUndefined()
    expect(button(mountControls(0.1004), 'Уменьшить масштаб').attributes('disabled')).toBeDefined()
    expect(button(mountControls(1), 'Увеличить масштаб').attributes('disabled')).toBeUndefined()
  })

  it('«Показать всю диаграмму» доступна всегда — даже на пределе масштаба', () => {
    expect(button(mountControls(2.5), 'Показать всю диаграмму').attributes('disabled')).toBeUndefined()
  })
})
