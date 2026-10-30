import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportTemplateFormModal from '../ReportTemplateFormModal.vue'
import type { ReportTemplate } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const templateFixture: ReportTemplate = {
  id: 't-1',
  name: 'Реестр устройств',
  description: 'Старое описание',
  format: 'docx',
  config: { blocks: [{ type: 'heading', text: 'Реестр устройств' }] },
  created_at: null,
  updated_at: null,
}

beforeEach(() => {
  setActivePinia(createPinia()) // компонент читает authStore.canWrite (режим просмотра для роли viewer)
  document.body.innerHTML = ''
})

describe('ReportTemplateFormModal.vue — создание', () => {
  it('без названия показывает ошибку и не отправляет запрос', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateFormModal, { props: { template: null } })

    await wrapper.find('.modal-foot button.btn-primary').trigger('click')

    expect(wrapper.text()).toContain('Укажите название шаблона')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('создаёт шаблон с выбранным форматом и эмитит saved', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ ...templateFixture, format: 'xlsx' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateFormModal, { props: { template: null } })

    await wrapper.find('input[type="text"]').setValue('Новый отчёт')
    await wrapper.find('select').setValue('xlsx')
    await wrapper.find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    const body = JSON.parse(fetchMock.mock.calls[0][1]!.body as string)
    expect(body.name).toBe('Новый отчёт')
    expect(body.format).toBe('xlsx')
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('формат доступен для выбора при создании (select не заблокирован)', () => {
    const wrapper = mount(ReportTemplateFormModal, { props: { template: null } })
    expect((wrapper.find('select').element as HTMLSelectElement).disabled).toBe(false)
  })
})

describe('ReportTemplateFormModal.vue — переименование', () => {
  it('подставляет текущие название/описание и блокирует смену формата', () => {
    const wrapper = mount(ReportTemplateFormModal, { props: { template: templateFixture } })
    expect((wrapper.find('input[type="text"]').element as HTMLInputElement).value).toBe('Реестр устройств')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('Старое описание')
    expect((wrapper.find('select').element as HTMLSelectElement).disabled).toBe(true)
  })

  it('PUT округляет format/config из переданного шаблона неизменными, отправляет новые name/description', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplateFormModal, { props: { template: templateFixture } })

    await wrapper.find('input[type="text"]').setValue('Переименован')
    await wrapper.find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates/t-1')
    expect(init?.method).toBe('PUT')
    const body = JSON.parse(init!.body as string)
    expect(body).toEqual({ name: 'Переименован', description: 'Старое описание', format: 'docx', config: templateFixture.config })
  })

  it('при ошибке сервера показывает сообщение и не эмитит saved', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ detail: 'Шаблон с таким названием уже существует' }, 409)),
    )
    const wrapper = mount(ReportTemplateFormModal, { props: { template: templateFixture } })

    await wrapper.find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('уже существует')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })
})

describe('ReportTemplateFormModal.vue — общее', () => {
  it('кнопка "Отмена" эмитит close', async () => {
    const wrapper = mount(ReportTemplateFormModal, { props: { template: null } })
    await wrapper.find('.modal-foot button.btn-secondary').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
