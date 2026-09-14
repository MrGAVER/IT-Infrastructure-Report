import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InformationSystemFormModal from '../InformationSystemFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import type { InformationSystem } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }
const EMPTY_DETAILS = { departments: [], ips: [], protocols: [], devices: [], vms: [], containers: [], sources: [], placement_assets: [] }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts. Названо не
// просто "body", чтобы не конфликтовать с локальными переменными body = ...response.body
// внутри некоторых тестов ниже.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function findEditors(wrapper: ReturnType<typeof mount>) {
  // Порядок в шаблоне (InformationSystemFormModal.vue): подразделения, протоколы, источники,
  // места размещения — все 4 переиспользуют класс .nested-editor.
  const editors = wrapper.findAll('.nested-editor')
  return { departments: editors[0], protocols: editors[1], sources: editors[2], placementAssets: editors[3] }
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('InformationSystemFormModal.vue — миграция и сохранение вложенных связей', () => {
  it('мигрирует legacy device/ip в единый источник при пустом sources', async () => {
    const system: InformationSystem = {
      id: 'is-1',
      number: null,
      name: 'ИС Тест',
      type: 'is',
      description: null,
      purpose: null,
      localization: null,
      support_organization_id: null,
      support_method_id: null,
      process_description: null,
      siem_enabled: false,
      crypto_protection_enabled: false,
      crypto_protection_description_id: null,
      status: 'active',
    }
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/information-systems/is-1/details') && method === 'GET') {
          return jsonResponse({
            ...EMPTY_DETAILS,
            devices: [{ id: 'd-1', physical_device_id: 'dev-1', role: 'основной сервер' }],
            ips: [{ id: 'ip-1', ip_address: '10.0.0.5', purpose: 'мониторинг', virtual_machine_id: null, physical_device_id: 'dev-1', external_interaction: false }],
          })
        }
        if (url.includes('/information-systems/is-1/details') && method === 'PUT') {
          return jsonResponse({ ok: true })
        }
        if (method === 'PUT' && url.includes('/resources/information-systems/is-1') && !url.includes('/details')) {
          return jsonResponse(system)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const detailsSave = calls.find((c) => c.method === 'PUT' && c.url.includes('/details'))
    const body = detailsSave!.body as { sources: unknown[]; devices: unknown[]; vms: unknown[]; ips: unknown[] }
    expect(body.sources).toEqual([
      { id: undefined, source_type: 'device', physical_device_id: 'dev-1', virtual_machine_id: null, container_id: null, ip_address: '10.0.0.5', purpose: 'мониторинг', role: 'основной сервер', external_interaction: false },
    ])
    expect(body.devices).toEqual([])
    expect(body.vms).toEqual([])
    expect(body.ips).toEqual([])
  })

  it('не запускает миграцию повторно, если sources уже заполнен', async () => {
    const system: InformationSystem = {
      id: 'is-2',
      number: null,
      name: 'ИС Тест 2',
      type: 'is',
      description: null,
      purpose: null,
      localization: null,
      support_organization_id: null,
      support_method_id: null,
      process_description: null,
      siem_enabled: false,
      crypto_protection_enabled: false,
      crypto_protection_description_id: null,
      status: 'active',
    }
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/information-systems/is-2/details') && method === 'GET') {
          return jsonResponse({
            ...EMPTY_DETAILS,
            // "Осколки" старых таблиц, которые НЕ должны попасть в sources повторно —
            // sources уже не пуст, значит миграция не запускается (см. migrateLegacyToSources).
            devices: [{ id: 'd-9', physical_device_id: 'dev-9', role: 'устаревшая запись' }],
            sources: [{ id: 'src-1', source_type: 'manual', physical_device_id: null, virtual_machine_id: null, container_id: null, ip_address: '1.1.1.1', purpose: '', role: '', external_interaction: false }],
          })
        }
        if (method === 'PUT' && url.includes('/resources/information-systems/is-2') && !url.includes('/details')) {
          return jsonResponse(system)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const detailsSave = calls.find((c) => c.method === 'PUT' && c.url.includes('/details'))
    const body = detailsSave!.body as { sources: Array<{ id?: string; physical_device_id: string | null }> }
    expect(body.sources).toHaveLength(1)
    expect(body.sources[0]).toMatchObject({ id: 'src-1', physical_device_id: null, ip_address: '1.1.1.1' })
  })

  it('создаёт новую ИС и сохраняет подразделение, протокол и источник', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['departments'] = [{ id: 'dep-1', name: 'Отдел ИБ' }]
    catalogs.protocolPortCatalog = [{ id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null }]
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    const editors = findEditors(wrapper)
    await editors.departments.find('button.add-btn').trigger('click')
    await editors.protocols.find('button.add-btn').trigger('click')
    await editors.sources.find('button.add-btn').trigger('click')

    await editors.departments.find('select').setValue('dep-1')
    await editors.protocols.find('.col-catalog select').setValue('cat-https')
    await editors.sources.find('.source-grid input').setValue('192.168.1.1') // IP при типе "вручную" по умолчанию

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/information-systems')) {
          return jsonResponse({ id: 'is-new', name: 'new-is' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[type="text"]').setValue('new-is')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const detailsSave = calls.find((c) => c.method === 'PUT' && c.url.includes('/information-systems/is-new/details'))
    const body = detailsSave!.body as { departments: unknown[]; protocols: unknown[]; sources: unknown[] }
    expect(body.departments).toEqual([{ id: undefined, department_id: 'dep-1' }])
    expect(body.protocols).toEqual([{ id: undefined, protocol_catalog_id: 'cat-https', protocol: 'HTTPS', port: 443, description: null }])
    expect(body.sources).toEqual([
      { id: undefined, source_type: 'manual', physical_device_id: null, virtual_machine_id: null, container_id: null, ip_address: '192.168.1.1', purpose: null, role: null, external_interaction: false },
    ])
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('фикс п.3: не сохраняет ИС с некорректным IP-адресом источника', async () => {
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    const editors = findEditors(wrapper)
    await editors.sources.find('button.add-btn').trigger('click')
    await editors.sources.find('.source-grid input.col-ip').setValue('не ip адрес')
    await wrapper.find('input[type="text"]').setValue('new-is')

    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Некорректный IP-адрес')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('не отправляет пустые строки подразделений/протоколов и источники "вручную" без IP', async () => {
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    const editors = findEditors(wrapper)
    await editors.departments.find('button.add-btn').trigger('click') // без выбора
    await editors.protocols.find('button.add-btn').trigger('click') // без выбора
    await editors.sources.find('button.add-btn').trigger('click') // manual, IP не заполнен

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/information-systems')) {
          return jsonResponse({ id: 'is-new2', name: 'new-is-2' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[type="text"]').setValue('new-is-2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const detailsSave = calls.find((c) => c.method === 'PUT' && c.url.includes('/details'))
    const body = detailsSave!.body as { departments: unknown[]; protocols: unknown[]; sources: unknown[] }
    expect(body.departments).toEqual([])
    expect(body.protocols).toEqual([])
    expect(body.sources).toEqual([])
  })

  it('быстрое добавление организации техподдержки подставляет её в форму', async () => {
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/support-organizations')) {
          return jsonResponse({ id: 'so-new', name: 'ООО "Технический партнёр"' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('.lookup-row button').trigger('click') // организация техподдержки — первое lookup-поле формы
    await teleportedContent().find('input[type="text"]').setValue('ООО "Технический партнёр"')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('so-new')
  })

  it('п.3: длинное наименование ИС показывает подсказку через секунду наведения', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
      const input = wrapper.find('input[maxlength="500"]') // "Наименование"
      await input.setValue('Автоматизированная информационная система очень длинного наименования')
      Object.defineProperty(input.element, 'scrollWidth', { value: 300, configurable: true })
      Object.defineProperty(input.element, 'clientWidth', { value: 100, configurable: true })

      await input.trigger('mouseenter')
      vi.advanceTimersByTime(1000)
      expect(document.querySelector('.truncate-tooltip-popup')?.textContent).toBe(
        'Автоматизированная информационная система очень длинного наименования',
      )
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('фикс п.2: копирование информационной системы ("copyFrom")', () => {
  const sourceSystem: InformationSystem = {
    id: 'is-src',
    number: null,
    name: 'ИС Донор',
    type: 'is',
    description: null,
    purpose: null,
    localization: null,
    support_organization_id: null,
    support_method_id: null,
    process_description: null,
    siem_enabled: false,
    crypto_protection_enabled: false,
    crypto_protection_description_id: null,
    status: 'active',
  }

  it('аудит fix/usability-batch4 (находка №5): одновременная передача system и copyFrom — предупреждение в консоль, побеждает system (edit)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_DETAILS)))
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const editedSystem: InformationSystem = { ...sourceSystem, id: 'is-edit', name: 'ИС Редактируемая' }
    const wrapper = mount(InformationSystemFormModal, { props: { system: editedSystem, copyFrom: sourceSystem } })
    await flushPromises()

    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('используется system'))
    expect(wrapper.find('h2').text()).toContain('Редактировать') // system выигрывает — это по-прежнему edit
  })

  it('форма открывается в режиме создания, name (уникален) очищен, вложенные связи донора — без его id', async () => {
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/information-systems/is-src/details') && method === 'GET') {
          return jsonResponse({
            ...EMPTY_DETAILS,
            departments: [{ id: 'dep-link-src', department_id: 'dep-1' }],
            sources: [{ id: 'src-src', source_type: 'manual', physical_device_id: null, virtual_machine_id: null, container_id: null, ip_address: '10.0.0.9', purpose: '', role: '', external_interaction: false }],
          })
        }
        if (method === 'POST' && url.endsWith('/resources/information-systems')) {
          return jsonResponse({ id: 'is-new', name: 'ИС Копия' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system: null, copyFrom: sourceSystem } })
    await flushPromises()

    expect(wrapper.find('h2').text()).not.toContain('Редактировать')
    expect(wrapper.find('input[maxlength="500"]').element).toHaveProperty('value', '') // name уникален — очищен

    await wrapper.find('input[maxlength="500"]').setValue('ИС Копия')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const detailsSave = calls.find((c) => c.method === 'PUT' && c.url.includes('/information-systems/is-new/details'))
    const body = detailsSave!.body as { departments: Array<{ id?: string; department_id: string }>; sources: Array<{ id?: string; ip_address: string }> }
    expect(body.departments).toEqual([{ id: undefined, department_id: 'dep-1' }]) // подгружено у донора, id обнулён
    expect(body.sources[0].id).toBeUndefined()
    expect(body.sources[0].ip_address).toBe('10.0.0.9')
    // Копия создаёт НОВУЮ ИС (POST) и её собственные details (PUT .../is-new/details) — донор не трогается.
    expect(calls.some((c) => c.url.includes('/information-systems/is-src/details') && c.method === 'PUT')).toBe(false)
  })
})
