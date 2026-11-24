// Экран «Проверка данных»: находки сервера, фильтры, одобрение, окно редактирования по имени объекта, пустые состояния, ошибка, страницы.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ConsistencyView from '../ConsistencyView.vue'
import type { ConsistencyReport } from '../../api/consistency'
import { useAuthStore } from '../../stores/auth'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useVMsStore } from '../../stores/vms'
import { approvalOf, approvedFinding, finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'

let calls: { method: string; url: string; body: unknown }[]

/** Сервер проверок: отчёт и каталог правил; запись (POST/DELETE) отвечает `write`. */
function stubServer(report: () => Response | ConsistencyReport, write: (method: string) => Response = () => new Response('{}', { status: 500 })) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : null })
      if (method !== 'GET') return write(method)
      if (url.endsWith('/consistency/rules')) return new Response(JSON.stringify({ rules: RULES }))
      const body = report()
      return body instanceof Response ? body : new Response(JSON.stringify(body))
    }),
  )
}

/** Окна редактирования заменены заглушками: форма устройства тянет за собой справочники, а здесь важно только что и с чем открыто. */
const editorStub = (kind: string, prop: string) =>
  defineComponent({
    props: { [prop]: { type: Object, default: null } },
    emits: ['close', 'saved'],
    setup(props, { emit }) {
      return () =>
        h('div', { class: 'editor-stub', 'data-kind': kind, 'data-id': (props[prop] as { id: string }).id }, [
          h('button', { class: 'stub-save', onClick: () => emit('saved', {}) }),
          h('button', { class: 'stub-close', onClick: () => emit('close') }),
        ])
    },
  })
const STUBS = {
  DeviceFormModal: editorStub('device', 'device'),
  VMFormModal: editorStub('vm', 'vm'),
  ContainerFormModal: editorStub('container', 'container'),
  InformationSystemFormModal: editorStub('system', 'system'),
}

async function mountView() {
  const wrapper = mount(ConsistencyView, { global: { stubs: STUBS } })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountView>>
const rows = (wrapper: Wrapper) => wrapper.findAll('tbody tr').filter((row) => !row.find('[data-empty]').exists())
const chip = (wrapper: Wrapper, text: string) => wrapper.findAll('.chip-group button').find((button) => button.text().startsWith(text))!
const buttonByText = (wrapper: Wrapper, text: string) => wrapper.findAll('button').find((button) => button.text() === text)!

const MIXED = [
  finding({
    rule: 'invalid_ip',
    severity: 'error',
    entity_type: 'virtual_machine',
    entity_id: 'vm-1',
    entity_name: 'vm-1',
    message: 'vm-1: «10.0.0.1/24» не похоже на IP-адрес.',
  }),
  finding(),
  finding({
    rule: 'vm_without_host',
    category: 'completeness',
    sheet: 4,
    entity_type: 'virtual_machine',
    entity_id: 'vm-2',
    entity_name: 'orphan',
    message: 'orphan: не указано физическое устройство.',
  }),
]

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('ConsistencyView', () => {
  it('показывает счётчики по важности и по строке на каждую находку', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()

    const cards = wrapper.findAll('.stat-card').map((card) => card.text())
    expect(cards).toEqual(['3Требуют внимания', '1Ошибки', '2Предупреждения', '0Сведения', '0Одобрено'])
    expect(rows(wrapper)).toHaveLength(3)
    expect(rows(wrapper)[0].text()).toContain('Ошибка')
  })

  it('название правила берётся из каталога, а категория подписана человеческим языком', async () => {
    stubServer(() => reportOf([MIXED[2]]))
    const wrapper = await mountView()

    expect(rows(wrapper)[0].text()).toContain('Виртуальная машина не привязана к устройству')
    expect(rows(wrapper)[0].text()).toContain('Пробел в данных')
    expect(rows(wrapper)[0].text()).toContain('Лист 4 — виртуальные машины')
  })

  it('чип важности и поиск сужают список, «Все» возвращает его', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()
    // «Все» есть в двух группах (важность и одобрение): берём чипы именно группы «Важность».
    const severity = (text: string) => wrapper.findAll('.chip-group[aria-label="Важность"] button').find((button) => button.text() === text)!

    await severity('Ошибка').trigger('click')
    expect(rows(wrapper)).toHaveLength(1)

    await severity('Все').trigger('click')
    await wrapper.find('.search-box input').setValue('ORPHAN')
    expect(rows(wrapper)).toHaveLength(1)
    expect(rows(wrapper)[0].text()).toContain('orphan')
  })

  it('фильтрация идёт на клиенте: выбор фильтра не делает новых запросов', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()
    const before = calls.length

    await wrapper.find('select[aria-label="Категория"]').setValue('completeness')

    expect(calls).toHaveLength(before)
    expect(rows(wrapper)).toHaveLength(1)
  })

  it('когда проблем нет — сообщает об этом без кнопки создания и без «Сбросить фильтры»', async () => {
    stubServer(() => reportOf([]))
    const wrapper = await mountView()

    expect(wrapper.find('[data-empty="registry"]').text()).toBe('Противоречий и пробелов в данных не найдено.')
    expect(wrapper.find('[data-action="create"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="reset-filters"]').exists()).toBe(false)
  })

  it('когда фильтры ничего не оставили — предлагает сбросить их, и сброс возвращает находки', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()

    await wrapper.find('.search-box input').setValue('нет такого объекта')
    expect(wrapper.find('[data-empty="filtered"]').exists()).toBe(true)

    await wrapper.find('[data-action="reset-filters"]').trigger('click')
    expect(rows(wrapper)).toHaveLength(3)
  })

  it('ошибка сервера не выглядит как «всё в порядке»: показывается причина, «Повторить» читает отчёт заново', async () => {
    let failing = true
    stubServer(() => (failing ? new Response(JSON.stringify({ detail: 'База недоступна' }), { status: 500 }) : reportOf(MIXED)))
    const wrapper = await mountView()

    expect(wrapper.find('[role="alert"]').text()).toContain('Не удалось выполнить проверку')
    expect(wrapper.find('[data-empty]').exists()).toBe(false)

    failing = false
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(rows(wrapper)).toHaveLength(3)
  })

  it('если сервер вернул не все находки — предупреждает, что часть не видна', async () => {
    stubServer(() => reportOf(MIXED, { total: 7000, returned: 3, truncated: true }))
    const wrapper = await mountView()

    expect(wrapper.find('[data-kind="incomplete"]').exists()).toBe(true)
  })

  it('разбивает находки на страницы по 10 и листает их', async () => {
    const many = Array.from({ length: 25 }, (_, index) => finding({ entity_id: `10.0.0.${index}`, entity_name: `10.0.0.${index}` }))
    stubServer(() => reportOf(many))
    const wrapper = await mountView()

    expect(rows(wrapper)).toHaveLength(10)
    expect(wrapper.find('.table-foot').text()).toContain('Показано 1–10 из 25')

    await wrapper.find('button[aria-label="Следующая страница"]').trigger('click')
    expect(wrapper.find('.table-foot').text()).toContain('Показано 11–20 из 25')
  })
})

describe('одобрение проблем', () => {
  const approved = approvedFinding({ entity_name: 'допустимая', message: 'допустимая: общий адрес' }, { comment: 'общий адрес VRRP', approved_by: 'anna' })

  it('одобренные по умолчанию скрыты, но посчитаны; чип «Одобренные» показывает их с автором, датой и комментарием', async () => {
    stubServer(() => reportOf([MIXED[0], approved]))
    const wrapper = await mountView()

    expect(rows(wrapper)).toHaveLength(1)
    expect(chip(wrapper, 'Требуют внимания').text()).toBe('Требуют внимания (1)')
    expect(wrapper.findAll('.stat-card').map((card) => card.text())).toContain('1Одобрено')

    await chip(wrapper, 'Одобренные').trigger('click')

    expect(rows(wrapper)).toHaveLength(1)
    expect(rows(wrapper)[0].find('.approved-badge').text()).toBe('Одобрено')
    expect(rows(wrapper)[0].find('.approval-note').text()).toMatch(/Одобрено: anna, 23\.11\.2026.*— общий адрес VRRP/)
  })

  it('«Все» показывает и требующие внимания, и одобренные', async () => {
    stubServer(() => reportOf([MIXED[0], approved]))
    const wrapper = await mountView()

    await chip(wrapper, 'Все').trigger('click')

    expect(rows(wrapper)).toHaveLength(2)
  })

  it('когда остались только одобренные — об этом сказано прямо, а не «проблем не найдено»', async () => {
    stubServer(() => reportOf([approved]))
    const wrapper = await mountView()

    expect(wrapper.find('[data-empty="registry"]').text()).toBe('Все найденные проблемы одобрены.')
  })

  it('«Одобрить» открывает окно с проблемой; подтверждение отправляет отпечаток и комментарий, строка уходит из списка', async () => {
    stubServer(
      () => reportOf(MIXED),
      () => new Response(JSON.stringify({ created: true, approval: approvalOf({ comment: 'VRRP' }) })),
    )
    const wrapper = await mountView()

    await buttonByText(rows(wrapper)[1] as unknown as Wrapper, 'Одобрить').trigger('click')
    expect(wrapper.find('[role="dialog"]').text()).toContain(MIXED[1].message)
    await wrapper.find('textarea').setValue('VRRP')
    await wrapper.find('.actions .btn-primary').trigger('click')
    await flushPromises()

    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ fingerprint: MIXED[1].fingerprint, comment: 'VRRP' })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(rows(wrapper)).toHaveLength(2)
    expect(wrapper.findAll('.stat-card').map((card) => card.text())).toContain('1Одобрено')
  })

  it('отказ сервера: окно остаётся открытым, находка не считается одобренной', async () => {
    stubServer(
      () => reportOf(MIXED),
      () => new Response(JSON.stringify({ detail: 'Сбой' }), { status: 500 }),
    )
    const wrapper = await mountView()

    await buttonByText(rows(wrapper)[1] as unknown as Wrapper, 'Одобрить').trigger('click')
    await wrapper.find('.actions .btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(rows(wrapper)).toHaveLength(3)
  })

  it('«Отозвать одобрение» шлёт DELETE и возвращает находку в список «требуют внимания»', async () => {
    const mine = approvedFinding({ entity_name: 'допустимая' }, { id: 'appr-9' })
    stubServer(
      () => reportOf([mine]),
      () => new Response(null, { status: 204 }),
    )
    const wrapper = await mountView()
    await chip(wrapper, 'Одобренные').trigger('click')

    await buttonByText(wrapper, 'Отозвать одобрение').trigger('click')
    await flushPromises()

    expect(calls.find((call) => call.method === 'DELETE')?.url).toMatch(/approvals\/appr-9$/)
    expect(rows(wrapper)).toHaveLength(0) // в чипе «Одобренные» её больше нет
    await chip(wrapper, 'Требуют внимания').trigger('click')
    expect(rows(wrapper)).toHaveLength(1)
  })

  it('наблюдатель видит одобрения, но не получает ни кнопок действий, ни столбца «Действие»', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'viewer', role: 'viewer', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    stubServer(() => reportOf([MIXED[0], approved]))
    const wrapper = await mountView()
    await chip(wrapper, 'Все').trigger('click')

    expect(wrapper.text()).not.toContain('Действие')
    expect(wrapper.findAll('tbody .btn')).toHaveLength(0)
    expect(wrapper.text()).toContain('Одобрено: anna')
  })
})

describe('окно редактирования по имени объекта', () => {
  const device = { id: 'dev-1', system_name: 'srv-1' }

  function stores() {
    const devices = useDevicesStore()
    devices.all = [device] as never
    devices.loaded = true
    const vms = useVMsStore()
    vms.all = [{ id: 'vm-1', name: 'vm-1' }] as never
    vms.loaded = true
    const containers = useContainersStore()
    containers.all = [{ id: 'c-1', name: 'c-1' }] as never
    containers.loaded = true
    const systems = useInformationSystemsStore()
    systems.all = [{ id: 'is-1', name: 'ИС' }] as never
    systems.loaded = true
    return { devices, vms, containers, systems }
  }

  const named = (wrapper: Wrapper, name: string) => wrapper.findAll('.entity-link').find((link) => link.text() === name)!

  it.each([
    ['physical_device', 'dev-1', 'device'],
    ['virtual_machine', 'vm-1', 'vm'],
    ['container', 'c-1', 'container'],
    ['information_system', 'is-1', 'system'],
  ])('имя объекта типа %s открывает его окно редактирования', async (type, id, kind) => {
    stores()
    stubServer(() => reportOf([finding({ rule: 'vm_without_host', entity_type: type, entity_id: id, entity_name: `имя-${id}`, message: 'м' })]))
    const wrapper = await mountView()

    await named(wrapper, `имя-${id}`).trigger('click')
    await flushPromises()

    const stub = wrapper.find('.editor-stub')
    expect(stub.attributes('data-kind')).toBe(kind)
    expect(stub.attributes('data-id')).toBe(id)
  })

  it('у находки про повтор IP открываются устройства-владельцы, а не сам адрес', async () => {
    stores()
    stubServer(() =>
      reportOf([
        finding({
          details: {
            holders: [
              { entity_type: 'physical_device', entity_id: 'dev-1', name: 'srv-1', place: 'Gi0/1' },
              { entity_type: 'virtual_machine', entity_id: 'vm-1', name: 'vm-1', place: null },
            ],
          },
        }),
      ]),
    )
    const wrapper = await mountView()

    expect(wrapper.findAll('.entity-link').map((link) => link.text())).toEqual(['srv-1', 'vm-1'])
    await named(wrapper, 'vm-1').trigger('click')
    await flushPromises()
    expect(wrapper.find('.editor-stub').attributes('data-kind')).toBe('vm')
  })

  it('объект, которого уже нет в справочнике, окно не открывает — показывается сообщение', async () => {
    stores()
    stubServer(() =>
      reportOf([finding({ rule: 'vm_without_host', entity_type: 'virtual_machine', entity_id: 'vm-gone', entity_name: 'удалённая', message: 'м' })]),
    )
    const wrapper = await mountView()

    await named(wrapper, 'удалённая').trigger('click')
    await flushPromises()

    expect(wrapper.find('.editor-stub').exists()).toBe(false)
  })

  it('после сохранения справочник и проверка перечитываются, а исправленная проблема исчезает', async () => {
    const { vms } = stores()
    const reload = vi.spyOn(vms, 'reload').mockResolvedValue(undefined as never)
    let fixed = false
    stubServer(() =>
      reportOf(fixed ? [] : [finding({ rule: 'vm_without_host', entity_type: 'virtual_machine', entity_id: 'vm-1', entity_name: 'vm-1', message: 'м' })]),
    )
    const wrapper = await mountView()
    await named(wrapper, 'vm-1').trigger('click')
    await flushPromises()

    fixed = true
    await wrapper.find('.stub-save').trigger('click')
    await flushPromises()

    expect(reload).toHaveBeenCalledOnce()
    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(2)
    expect(wrapper.find('.editor-stub').exists()).toBe(false)
    expect(rows(wrapper)).toHaveLength(0)
  })

  it('закрытие окна без сохранения проверку не перезапускает', async () => {
    stores()
    stubServer(() => reportOf([finding({ rule: 'vm_without_host', entity_type: 'virtual_machine', entity_id: 'vm-1', entity_name: 'vm-1', message: 'м' })]))
    const wrapper = await mountView()
    await named(wrapper, 'vm-1').trigger('click')
    await flushPromises()
    const before = calls.length

    await wrapper.find('.stub-close').trigger('click')

    expect(wrapper.find('.editor-stub').exists()).toBe(false)
    expect(calls).toHaveLength(before)
  })

  it('IP-адрес без владельцев — просто текст; наблюдателю имя объекта — ссылка на раздел, а не кнопка редактирования', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'viewer', role: 'viewer', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    stubServer(() =>
      reportOf([finding(), finding({ rule: 'vm_without_host', entity_type: 'virtual_machine', entity_id: 'vm-1', entity_name: 'vm-1', message: 'м' })]),
    )
    const wrapper = await mountView()

    expect(wrapper.findAll('.entity-link')).toHaveLength(0)
    expect(wrapper.findAll('tbody a').map((link) => [link.text(), link.attributes('href')])).toEqual([['vm-1', '/vms']])
    expect(rows(wrapper)[0].find('.object-cell').text()).toBe('10.0.0.5')
  })
})

describe('выборка из параметров ссылки', () => {
  async function mountAt(url: string) {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/consistency', component: ConsistencyView }] })
    await router.push(url)
    await router.isReady()
    const wrapper = mount(ConsistencyView, { global: { plugins: [router], stubs: STUBS } })
    await flushPromises()
    return wrapper
  }

  it('?sheet=4 открывает экран сразу с этим листом: блок «Готовность отчёта» ведёт именно сюда', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountAt('/consistency?sheet=4')

    expect((wrapper.find('select[aria-label="Лист отчёта"]').element as HTMLSelectElement).value).toBe('4')
    expect(rows(wrapper)).toHaveLength(1)
    expect(rows(wrapper)[0].text()).toContain('orphan')
  })

  it('испорченные параметры (?sheet=99&category=x) экран не обнуляют: открывается полный список', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountAt('/consistency?sheet=99&category=x')

    expect(rows(wrapper)).toHaveLength(3)
  })

  it('без параметров фильтров нет, а «Сбросить» после перехода по ссылке возвращает полный список', async () => {
    stubServer(() => reportOf([MIXED[0]]))
    const wrapper = await mountAt('/consistency?category=completeness')

    expect(wrapper.find('[data-empty="filtered"]').exists()).toBe(true)
    await wrapper.find('[data-action="reset-filters"]').trigger('click')
    expect(rows(wrapper)).toHaveLength(1)
  })
})
