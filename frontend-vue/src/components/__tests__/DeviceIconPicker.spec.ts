import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useCatalogsStore } from '../../stores/catalogs'
import DeviceIconPicker from '../DeviceIconPicker.vue'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('DeviceIconPicker.vue', () => {
  it('пустой modelValue показывает пункт "Автоматически"', () => {
    const wrapper = mount(DeviceIconPicker, { props: { modelValue: null } })
    const select = wrapper.find('select')
    expect((select.element as HTMLSelectElement).value).toBe('')
  })

  it('выбор существующей иконки эмитит update:modelValue с её id', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['diagram-icons'] = [{ id: 'icon-1', name: 'Cisco 2960', svg_markup: '<svg/>' }]
    const wrapper = mount(DeviceIconPicker, { props: { modelValue: null } })

    await wrapper.find('select').setValue('icon-1')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['icon-1'])
  })

  it('показывает предпросмотр svg_markup выбранной иконки', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['diagram-icons'] = [{ id: 'icon-1', name: 'Cisco 2960', svg_markup: '<circle class="mark" r="4"/>' }]
    const wrapper = mount(DeviceIconPicker, { props: { modelValue: 'icon-1' } })
    expect(wrapper.find('.preview .mark').exists()).toBe(true)
  })

  it('загрузка своей иконки создаёт запись в каталоге и выбирает её (раздел 13 ТЗ: сохраняет diagram_icon_id)', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/resources/diagram-icons')) {
        return jsonResponse({ id: 'icon-new', name: 'Моя иконка', svg_markup: '<svg/>' }, 201)
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const catalogs = useCatalogsStore()
    const wrapper = mount(DeviceIconPicker, { props: { modelValue: null } })

    await wrapper.find('button').trigger('click') // "+ Загрузить свою иконку"
    await wrapper.find('input[type="text"]').setValue('Моя иконка')
    await wrapper.find('textarea').setValue('<svg><rect/></svg>')
    await wrapper.findAll('button').find((b) => b.text().includes('Сохранить иконку'))!.trigger('click')
    await flushPromises()

    const postCall = fetchMock.mock.calls.find(([u, init]) => (init?.method ?? 'GET') === 'POST' && (u as string).includes('diagram-icons'))
    expect(postCall).toBeTruthy()
    const payload = JSON.parse((postCall![1] as RequestInit).body as string)
    expect(payload).toEqual({ name: 'Моя иконка', svg_markup: '<svg><rect/></svg>' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['icon-new'])
    expect(catalogs.items['diagram-icons']).toContainEqual({ id: 'icon-new', name: 'Моя иконка', svg_markup: '<svg/>' })
  })

  it('не отправляет запрос при пустом названии или SVG', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(DeviceIconPicker, { props: { modelValue: null } })

    await wrapper.find('button').trigger('click')
    await wrapper.findAll('button').find((b) => b.text().includes('Сохранить иконку'))!.trigger('click')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('diagram-icons'), expect.objectContaining({ method: 'POST' }))
  })
})
