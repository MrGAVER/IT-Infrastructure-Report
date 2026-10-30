import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InformationSystemFormModal from '../InformationSystemFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import type { InformationSystem } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }
const EMPTY_DETAILS = { departments: [], protocols: [], sources: [], placement_assets: [] }

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

describe('InformationSystemFormModal.vue — загрузка и сохранение вложенных связей', () => {
  it('загружает уже сохранённые sources и отправляет их обратно без изменений', async () => {
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
            sources: [
              {
                id: 'src-1',
                source_type: 'manual',
                owner_id: null,
                ips: [{ id: 'ip-1', ip_address: '1.1.1.1' }],
                purpose: '',
                role: '',
                external_interaction: false,
              },
            ],
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
    const body = detailsSave!.body as { sources: Array<{ id?: string; owner_id: string | null; ips: Array<{ ip_address: string }> }> }
    expect(body.sources).toHaveLength(1)
    expect(body.sources[0]).toMatchObject({ id: 'src-1', owner_id: null })
    expect(body.sources[0].ips).toEqual([{ id: 'ip-1', ip_address: '1.1.1.1' }])
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

    await editors.departments.find('.searchable-select input').trigger('focus')
    await editors.departments.find('.ss-option').trigger('mousedown') // единственная запись — «Отдел ИБ»
    await editors.protocols.find('.col-catalog .searchable-select input').trigger('focus')
    await editors.protocols.find('.col-catalog .ss-option').trigger('mousedown') // единственная запись — "443 / HTTPS"
    await editors.sources.find('.source-grid button.btn-link').trigger('click') // "+ IP-адрес" при типе "вручную" по умолчанию
    await editors.sources.find('.manual-ip-row input').setValue('192.168.1.1')

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
    expect(body.protocols).toEqual([{ id: undefined, protocol_catalog_id: 'cat-https', description: null }])
    expect(body.sources).toEqual([
      {
        id: undefined,
        source_type: 'manual',
        owner_id: null,
        ips: [{ id: undefined, ip_address: '192.168.1.1' }],
        purpose: null,
        role: null,
        external_interaction: false,
      },
    ])
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('фикс п.3: не сохраняет ИС с некорректным IP-адресом источника', async () => {
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    const editors = findEditors(wrapper)
    await editors.sources.find('button.add-btn').trigger('click')
    await editors.sources.find('.source-grid button.btn-link').trigger('click')
    await editors.sources.find('.manual-ip-row input').setValue('не ip адрес')
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

    // Фикс: поле теперь SearchableSelect, а не нативный <select> — читаем отображённую подпись
    // выбранной опции через её input, как и везде в тестах SearchableSelect (см.
    // DeviceFormModal.spec.ts). "Очистить" (.ss-clear) не мешает найти именно этот input: он
    // рендерится только когда значение уже выбрано, а перед созданием организации поле пустое.
    expect((wrapper.find('.searchable-select input').element as HTMLInputElement).value).toBe('ООО "Технический партнёр"')
  })

  it('СКЗИ — SearchableSelect: недоступен, пока не отмечено «Применяются сертифицированные СКЗИ», и сохраняет выбор', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['crypto-protection-means'] = [
      { id: 'cpm-1', name: 'ViPNet Client' },
      { id: 'cpm-2', name: 'КриптоПро CSP' },
    ]
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    // Поле «Средство криптографической защиты» — последнее lookup-поле перед вложенными редакторами.
    const cryptoField = wrapper.findAll('.field').find((f) => f.text().includes('Средство криптографической защиты'))!
    expect(cryptoField.find('select').exists()).toBe(false)
    expect(cryptoField.find('.lookup-row .searchable-select').exists()).toBe(true)
    expect(cryptoField.find('.searchable-select input').attributes('disabled')).toBeDefined()

    const checkboxes = wrapper.findAll('.checkbox-field input[type="checkbox"]') // 0 — SIEM, 1 — СКЗИ
    await checkboxes[1].setValue(true) // «Применяются сертифицированные СКЗИ»
    expect(cryptoField.find('.searchable-select input').attributes('disabled')).toBeUndefined()

    await cryptoField.find('.searchable-select input').trigger('focus')
    await cryptoField
      .findAll('.ss-option')
      .find((o) => o.text() === 'КриптоПро CSP')!
      .trigger('mousedown')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/information-systems')) return jsonResponse({ id: 'is-crypto', name: 'crypto-is' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )
    await wrapper.find('input[maxlength="500"]').setValue('crypto-is')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/information-systems'))
    expect(create!.body).toMatchObject({ crypto_protection_enabled: true, crypto_protection_description_id: 'cpm-2' })
  })

  it('организация и способ техподдержки — два SearchableSelect в одной строке формы, каждый растягивается на свою ячейку', async () => {
    const wrapper = mount(InformationSystemFormModal, { props: { system: null } })
    await flushPromises()

    const fields = wrapper.findAll('.field').filter((f) => /техническ|техподдержк/i.test(f.find('span').text()))
    expect(fields).toHaveLength(2)
    for (const field of fields) {
      expect(field.classes()).not.toContain('field-wide') // половина строки грида, а не отдельная строка
      expect(field.find('.lookup-row > .searchable-select').exists()).toBe(true)
    }
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
      expect(document.querySelector('.truncate-tooltip-popup')?.textContent).toBe('Автоматизированная информационная система очень длинного наименования')
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
  }

  it('аудит fix/usability-batch4 (находка №5): одновременная передача system и copyFrom — предупреждение в консоль, побеждает system (edit)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(EMPTY_DETAILS)),
    )
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
            sources: [
              {
                id: 'src-src',
                source_type: 'manual',
                owner_id: null,
                ips: [{ id: 'ip-src', ip_address: '10.0.0.9' }],
                purpose: '',
                role: '',
                external_interaction: false,
              },
            ],
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
    const body = detailsSave!.body as {
      departments: Array<{ id?: string; department_id: string }>
      sources: Array<{ id?: string; ips: Array<{ id?: string; ip_address: string }> }>
    }
    expect(body.departments).toEqual([{ id: undefined, department_id: 'dep-1' }]) // подгружено у донора, id обнулён
    expect(body.sources[0].id).toBeUndefined()
    // Донорский id вложенного IP тоже обнулён (см. комментарий у stripIds() в компоненте) — иначе
    // backend отклонил бы его 422 "IP не принадлежит выбранному источнику" (у новой source-строки
    // такого id ещё быть не может).
    expect(body.sources[0].ips).toEqual([{ id: undefined, ip_address: '10.0.0.9' }])
    // Копия создаёт НОВУЮ ИС (POST) и её собственные details (PUT .../is-new/details) — донор не трогается.
    expect(calls.some((c) => c.url.includes('/information-systems/is-src/details') && c.method === 'PUT')).toBe(false)
  })
})

describe('InformationSystemFormModal.vue — протоколы ИС как открытые порты ВМ', () => {
  const system: InformationSystem = {
    id: 'is-ports',
    number: null,
    name: 'ИС с портами',
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
  }

  // created — ответ на POST новой ИС (копирование); без него создание не ожидается.
  function stubBackend(protocols: unknown[], calls: Array<{ url: string; method: string; body?: unknown }>, created?: { id: string; name: string }) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/information-systems/is-ports/details') && method === 'GET') return jsonResponse({ ...EMPTY_DETAILS, protocols })
        if (method === 'PUT' && url.includes('/resources/information-systems/is-ports') && !url.includes('/details')) return jsonResponse(system)
        if (created && method === 'POST' && url.endsWith('/resources/information-systems')) return jsonResponse(created, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )
  }

  function seedCatalog() {
    useCatalogsStore().protocolPortCatalog = [
      { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
      { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
      { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
      { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
    ]
  }

  it('форма открывается с протоколами по возрастанию номера порта и отправляет их в этом порядке', async () => {
    seedCatalog()
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    stubBackend(
      [
        { id: 'p-https', protocol_catalog_id: 'cat-https', description: null },
        { id: 'p-ssh', protocol_catalog_id: 'cat-ssh', description: 'админ' },
      ],
      calls,
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const body = calls.find((c) => c.method === 'PUT' && c.url.includes('/details'))!.body as { protocols: Array<{ id: string; protocol_catalog_id: string }> }
    expect(body.protocols.map((p) => p.id)).toEqual(['p-ssh', 'p-https'])
  })

  it('повторяющийся номер порта блокирует сохранение: запросов на сервер нет, показана ошибка', async () => {
    seedCatalog()
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    stubBackend(
      [
        { id: 'p-1', protocol_catalog_id: 'cat-http', description: null },
        { id: 'p-2', protocol_catalog_id: 'cat-http-alt', description: null },
      ],
      calls,
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system } })
    await flushPromises()
    const before = calls.length
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.slice(before)).toEqual([])
    expect(wrapper.text()).toContain('Номера открытых портов не должны повторяться: 80.')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('копия ИС: протоколы упорядочены и приходят без id (создаются заново под новой ИС)', async () => {
    seedCatalog()
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    stubBackend(
      [
        { id: 'p-https', protocol_catalog_id: 'cat-https', description: null },
        { id: 'p-ssh', protocol_catalog_id: 'cat-ssh', description: null },
      ],
      calls,
      { id: 'is-copy', name: 'Копия' },
    )

    const wrapper = mount(InformationSystemFormModal, { props: { system: null, copyFrom: system } })
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('Копия')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const body = calls.find((c) => c.method === 'PUT' && c.url.includes('/details'))!.body as { protocols: Array<{ id?: string; protocol_catalog_id: string }> }
    expect(body.protocols).toEqual([
      { protocol_catalog_id: 'cat-ssh', description: null },
      { protocol_catalog_id: 'cat-https', description: null },
    ])
  })
})
