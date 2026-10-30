import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportTemplateVersionsModal from '../ReportTemplateVersionsModal.vue'
import type { ReportTemplate, ReportTemplateVersion } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const templateFixture: ReportTemplate = {
  id: 't-1',
  name: 'Реестр устройств',
  description: null,
  format: 'xlsx',
  config: {},
  created_at: null,
  updated_at: null,
}

const versionsFixture: ReportTemplateVersion[] = [
  { id: 'v-2', version_number: 2, name: 'Реестр устройств', description: 'после правки', format: 'xlsx', created_at: '2026-02-01T10:00:00Z' },
  { id: 'v-1', version_number: 1, name: 'Реестр устройств (черновик)', description: null, format: 'xlsx', created_at: '2026-01-15T08:30:00Z' },
]

beforeEach(() => {
  setActivePinia(createPinia()) // компонент читает authStore.canWrite («Восстановить» — только запись)
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})

describe('ReportTemplateVersionsModal.vue', () => {
  it('грузит и показывает список версий с номером и датой', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(versionsFixture)),
    )
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    expect(wrapper.text()).toContain('№2')
    expect(wrapper.text()).toContain('№1')
    expect(wrapper.text()).toContain('после правки')
    expect(wrapper.findAll('.version-row')).toHaveLength(2)
  })

  it('пустая история — сообщение вместо списка', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    expect(wrapper.text()).toContain('Версий пока нет')
    expect(wrapper.find('.version-row').exists()).toBe(false)
  })

  it('восстановление запрашивает подтверждение и эмитит restored с результатом', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return jsonResponse(versionsFixture)
      return jsonResponse({ ...templateFixture, name: 'Восстановлено' })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    await wrapper.findAll('.version-row button')[0].trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    const restoreCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
    expect(restoreCall?.[0]).toBe('/api/v1/report-templates/t-1/versions/v-2/restore')
    expect(wrapper.emitted('restored')?.[0][0]).toMatchObject({ name: 'Восстановлено' })
  })

  it('отказ от подтверждения — запрос на восстановление не отправляется', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const fetchMock = vi.fn(async () => jsonResponse(versionsFixture))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    await wrapper.findAll('.version-row button')[0].trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1) // только первоначальная загрузка списка версий
    expect(wrapper.emitted('restored')).toBeFalsy()
  })

  it('ошибка при восстановлении показывается, restored не эмитится', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return jsonResponse(versionsFixture)
      return jsonResponse({ detail: 'Версия не найдена' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    await wrapper.findAll('.version-row button')[0].trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Версия не найдена')
    expect(wrapper.emitted('restored')).toBeFalsy()
  })

  it('кнопка "Закрыть" эмитит close', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(versionsFixture)),
    )
    const wrapper = mount(ReportTemplateVersionsModal, { props: { template: templateFixture } })
    await flushPromises()

    await wrapper.find('.modal-foot button').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
