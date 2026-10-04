import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionsView from '../ConnectionsView.vue'
import ConnectionCanvasModal from '../../components/ConnectionCanvasModal.vue'
import PortConfigReviewModal from '../../components/PortConfigReviewModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { DEFAULT_PAGE_SIZE } from '../../stores/connectionsDashboard'
import type { Connection, ConnectionsSummary } from '../../api/types'

// DevicePortsModal.vue телепортируется в body (см. DevicePortsModal.spec.ts) — ищем там же.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function connection(id: string, overrides: Partial<Connection> = {}): Connection {
  return {
    id,
    source_interface_id: 'if-1',
    source_device_name: 'srv-01',
    source_interface_name: 'eth0',
    destination_interface_id: 'if-2',
    destination_device_name: 'sw-01',
    destination_interface_name: 'gi0/1',
    connection_type_id: 'ct-1',
    connection_type_name: 'Витая пара',
    is_active: true,
    description: '',
    source_port_role: 'data',
    destination_port_role: 'data',
    port_config_status: 'ok',
    source_vlan_mode: 'trunk', destination_vlan_mode: 'trunk', source_vlans: [], destination_vlans: [], port_config_diff: [],
    ...overrides,
  }
}

const connectionFixture = connection('conn-1')

// Страница дашборда (/api/v1/connections?…) и общий кэш (/api/v1/resources/connections?…) — разные запросы.
const PAGE_URL = /\/api\/v1\/connections\?/

interface Call { url: string; method: string; body?: Record<string, unknown> }
let calls: Call[]
const pageRequests = () => calls.filter((c) => c.method === 'GET' && PAGE_URL.test(c.url))
const lastPageParams = () => new URL(pageRequests().at(-1)!.url, 'http://x').searchParams
const approveRequests = () => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/connections/port-config/approve'))

interface ServerOptions {
  /** Строки, которые «сервер» отдаёт как страницу (поиск/фильтры клиент не применяет — их считает сервер). */
  rows?: Connection[]
  /** Сколько подключений под условиями (для пейджера); по умолчанию — число строк. */
  total?: number
  summary?: Partial<ConnectionsSummary>
  /** Ответы на прочие запросы (порты устройства и т.п.); undefined — ответ по умолчанию. */
  extra?: (call: Call) => Response | undefined
  /** Ошибка на запрос страницы. */
  pageError?: string
}

function installServer(options: ServerOptions = {}) {
  const rows = options.rows ?? []
  const summary: ConnectionsSummary = {
    total: rows.length,
    active: rows.filter((c) => c.is_active).length,
    inactive: rows.filter((c) => !c.is_active).length,
    mismatch: rows.filter((c) => c.port_config_status === 'mismatch').length,
    approved: rows.filter((c) => c.port_config_status === 'approved').length,
    ...options.summary,
  }
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      const custom = options.extra?.(call)
      if (custom) return custom
      if (call.method === 'GET' && PAGE_URL.test(url)) {
        if (options.pageError) return jsonResponse({ detail: options.pageError }, 500)
        return jsonResponse({ items: rows, total: options.total ?? rows.length, offset: 0, limit: DEFAULT_PAGE_SIZE, summary })
      }
      if (call.method === 'POST' && url.endsWith('/connections/port-config/approve')) {
        return jsonResponse({ items: [], skipped_ids: [], approved_count: options.total ?? rows.length })
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    }),
  )
}

async function mountView(options: ServerOptions = {}) {
  installServer(options)
  const catalogs = useCatalogsStore()
  catalogs.loaded = true
  if (!catalogs.items['interfaces']) catalogs.items['interfaces'] = []
  useDevicesStore().loaded = true
  const wrapper = mount(ConnectionsView)
  await flushPromises()
  return wrapper
}

const rowsText = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.findAll('tbody tr').map((r) => r.text())

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  installServer()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ConnectionsView.vue — управление портами прямо из строки таблицы', () => {
  it('открывает DevicePortsModal для устройства-источника, найденного через каталог интерфейсов', async () => {
    useCatalogsStore().items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]
    const wrapper = await mountView({
      rows: [connectionFixture],
      extra: (call) =>
        call.url.includes('/resources/interfaces') && call.method === 'GET'
          ? jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
          : undefined,
    })

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(body().text()).toContain('Порты устройства «srv-01»')
  })

  it('после сохранения портов перечитывает страницу подключений (могло измениться имя порта)', async () => {
    useCatalogsStore().items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]
    const wrapper = await mountView({
      rows: [connectionFixture],
      extra: (call) => {
        if (call.url.includes('/resources/interfaces') && call.method === 'GET') {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
        }
        if (call.method === 'PUT' && call.url.includes('/devices/dev-1/interfaces')) {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0-renamed' }] })
        }
        return undefined
      },
    })
    const before = pageRequests().length

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()
    await body().find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    expect(pageRequests().length).toBeGreaterThan(before)
    expect(body().text()).not.toContain('Порты устройства')
  })

  it('клик по кнопке порта для устройства, отсутствующего в каталоге интерфейсов, ничего не открывает', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] }) // каталог 'interfaces' пуст -> physical_device_id неизвестен

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(body().text()).not.toContain('Порты устройства')
  })
})

describe('ConnectionsView.vue — визуальный режим (фикс п.3.4, батч4)', () => {
  it('кнопка "Визуальный режим" открывает схему подключений', async () => {
    const wrapper = await mountView()

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(false)
    await wrapper.findAll('button').find((b) => b.text().includes('Визуальный режим'))!.trigger('click')

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(true)
  })

  it('после закрытия схемы перечитывает страницу подключений (могли добавиться новые перетаскиванием)', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('button').find((b) => b.text().includes('Визуальный режим'))!.trigger('click')
    const before = pageRequests().length

    await wrapper.findComponent(ConnectionCanvasModal).vm.$emit('close')
    await flushPromises()

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(false)
    expect(pageRequests().length).toBeGreaterThan(before)
  })
})

describe('ConnectionsView.vue — постраничная выборка с сервера', () => {
  it('при открытии запрашивает первую страницу и показывает только её строки', async () => {
    const wrapper = await mountView({ rows: [connection('a', { source_device_name: 'srv-A' }), connection('b', { source_device_name: 'srv-B' })], total: 1000 })

    const params = lastPageParams()
    expect(params.get('offset')).toBe('0')
    expect(params.get('limit')).toBe(String(DEFAULT_PAGE_SIZE))
    expect(rowsText(wrapper)).toHaveLength(2)
    expect(wrapper.find('.table-foot').text()).toContain('Показано 1–2 из 1000')
  })

  it('карточки-счётчики берутся из summary сервера, а не считаются по показанной странице', async () => {
    const wrapper = await mountView({
      rows: [connectionFixture],
      total: 1,
      summary: { total: 5000, active: 4800, inactive: 200, mismatch: 37, approved: 3 },
    })

    const cards = wrapper.findAll('.stat-card').map((c) => c.text())
    expect(cards.some((t) => t.includes('5000') && t.includes('Всего'))).toBe(true)
    expect(cards.some((t) => t.includes('4800'))).toBe(true)
    expect(cards.some((t) => t.includes('200'))).toBe(true)
    expect(cards.some((t) => t.includes('37'))).toBe(true)
  })

  it('пейджер не рисует кнопку на каждую страницу: при 1000 страниц — окно с многоточием', async () => {
    const wrapper = await mountView({ rows: [connectionFixture], total: DEFAULT_PAGE_SIZE * 1000 })

    const buttons = wrapper.findAll('.pager button')
    expect(buttons.length).toBeLessThanOrEqual(9) // «‹», первая, соседи, последняя, «›»
    expect(wrapper.find('.pager-gap').exists()).toBe(true)
    expect(buttons.map((b) => b.text())).toContain('1000')
  })

  it('поле «Показывать по»: варианты 8/16/32/64; выбор запрашивает у сервера новый limit и запоминается', async () => {
    localStorage.clear()
    const wrapper = await mountView({ rows: [connectionFixture], total: 100 })
    const select = wrapper.find('.table-foot select')

    expect(select.findAll('option').map((o) => o.text())).toEqual(['8', '16', '32', '64'])
    expect((select.element as HTMLSelectElement).value).toBe(String(DEFAULT_PAGE_SIZE))

    await select.setValue('32')
    await flushPromises()

    expect(lastPageParams().get('limit')).toBe('32')
    expect(lastPageParams().get('offset')).toBe('0')
    expect(wrapper.find('.table-foot').text()).toContain('из 100')
    expect(wrapper.findAll('.pager button').filter((b) => /^\d+$/.test(b.text()))).toHaveLength(4) // 100 / 32 → 4 страницы
    expect(localStorage.getItem('itr.pageSize.connections')).toBe('32')
  })

  it('после смены размера следующая страница запрашивается со смещением от нового размера', async () => {
    localStorage.clear()
    const wrapper = await mountView({ rows: [connectionFixture], total: 100 })
    await wrapper.find('.table-foot select').setValue('16')
    await flushPromises()

    await wrapper.find('[aria-label="Следующая страница"]').trigger('click')
    await flushPromises()

    expect(lastPageParams().get('offset')).toBe('16')
    expect(lastPageParams().get('limit')).toBe('16')
  })

  it('переход на следующую страницу запрашивает следующее смещение', async () => {
    const wrapper = await mountView({ rows: [connectionFixture], total: DEFAULT_PAGE_SIZE * 3 })

    await wrapper.find('[aria-label="Следующая страница"]').trigger('click')
    await flushPromises()

    expect(lastPageParams().get('offset')).toBe(String(DEFAULT_PAGE_SIZE))
    expect(wrapper.find('.table-foot').text()).toContain(`Показано ${DEFAULT_PAGE_SIZE + 1}–${DEFAULT_PAGE_SIZE + 1}`)
  })

  it('смена фильтра возвращает на первую страницу', async () => {
    const wrapper = await mountView({ rows: [connectionFixture], total: DEFAULT_PAGE_SIZE * 3 })
    await wrapper.find('[aria-label="Следующая страница"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-filter="mismatch"]').trigger('click')
    await flushPromises()

    expect(lastPageParams().get('offset')).toBe('0')
    expect(lastPageParams().get('port_config_status')).toBe('mismatch')
  })

  it('ошибка загрузки страницы показывается в таблице', async () => {
    const wrapper = await mountView({ pageError: 'База данных недоступна' })
    expect(wrapper.find('.error-banner').text()).toContain('База данных недоступна')
  })

  it('пустой результат — сообщение «Ничего не найдено»', async () => {
    const wrapper = await mountView({ rows: [], total: 0 })
    expect(wrapper.find('.empty-row').text()).toContain('Ничего не найдено')
  })
})

describe('ConnectionsView.vue — поиск на сервере', () => {
  // Только таймеры setTimeout/clearTimeout: flushPromises() использует setImmediate, который
  // нельзя подменять.
  const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

  it('запрос уходит после паузы в наборе, одним запросом на серию нажатий', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] })
    fakeTimers()
    const before = pageRequests().length

    const input = wrapper.find('.search-box input')
    await input.setValue('я')
    await input.setValue('яд')
    await input.setValue('ядро')
    vi.advanceTimersByTime(299)
    expect(pageRequests().length).toBe(before)
    vi.advanceTimersByTime(1)
    await flushPromises()

    expect(pageRequests().length).toBe(before + 1)
    expect(lastPageParams().get('q')).toBe('ядро')
    expect(lastPageParams().get('offset')).toBe('0')
  })

  it('смена фильтра отправляется сразу и отменяет ещё не отправленный поиск (без лишнего второго запроса)', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] })
    fakeTimers()
    const before = pageRequests().length

    await wrapper.find('.search-box input').setValue('ядро')
    await wrapper.find('[data-filter="approved"]').trigger('click')
    await flushPromises()
    expect(pageRequests().length).toBe(before + 1)
    expect(lastPageParams().get('q')).toBe('ядро')
    expect(lastPageParams().get('port_config_status')).toBe('approved')

    vi.advanceTimersByTime(1000)
    await flushPromises()
    expect(pageRequests().length).toBe(before + 1)
  })

  it('после закрытия экрана неотправленный поиск не уходит', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] })
    fakeTimers()
    const before = pageRequests().length

    await wrapper.find('.search-box input').setValue('ядро')
    wrapper.unmount()
    vi.advanceTimersByTime(1000)
    await flushPromises()

    expect(pageRequests().length).toBe(before)
  })

  it('фильтр активности передаётся серверу', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] })
    const buttons = wrapper.findAll('.chip-group')[0].findAll('button')

    await buttons.find((b) => b.text() === 'Неактивные')!.trigger('click')
    await flushPromises()

    expect(lastPageParams().get('is_active')).toBe('false')
  })
})

describe('ConnectionsView.vue — проверка конфигурации портов-соседей', () => {
  const mismatched = connection('conn-2', {
    source_device_name: 'srv-02', source_interface_name: 'idrac', destination_device_name: 'sw-02', destination_interface_name: 'gi0/7',
    source_port_role: 'management', destination_port_role: 'data', port_config_status: 'mismatch', port_config_diff: ['role'],
  })
  const approved = connection('conn-3', { ...mismatched, id: 'conn-3', source_device_name: 'srv-03', port_config_status: 'approved' })

  it('без расхождений баннер не показывается, а колонка «Конфигурация портов» содержит роль, режим и VLAN порта', async () => {
    const wrapper = await mountView({ rows: [connectionFixture] })

    expect(wrapper.find('.mismatch-banner').exists()).toBe(false)
    expect(wrapper.find('thead').text()).toContain('Конфигурация портов')
    expect(wrapper.find('thead').text()).not.toContain('Назначение линии')
    expect(wrapper.find('tbody').text()).toContain('Передача данных')
    expect(wrapper.find('.port-badge').exists()).toBe(false)
  })

  it('в строке без расхождений показывает режим и VLAN порта', async () => {
    const row = connection('conn-v', { source_vlan_mode: 'trunk', destination_vlan_mode: 'trunk', source_vlans: [10, 11, 12, 20], destination_vlans: [10, 11, 12, 20] })
    const wrapper = await mountView({ rows: [row] })

    expect(wrapper.find('.roles-cell').text()).toContain('trunk · VLAN 10–12, 20')
  })

  it('расхождение режима и VLAN: обе стороны с портом, режимом и VLAN, различающиеся значения выделены, бейдж называет грани', async () => {
    const row = connection('conn-m', {
      source_interface_name: 'eth0', destination_interface_name: 'gi0/1',
      source_port_role: 'data', destination_port_role: 'data',
      source_vlan_mode: 'trunk', destination_vlan_mode: 'access', source_vlans: [10, 20], destination_vlans: [10],
      port_config_status: 'mismatch', port_config_diff: ['mode', 'vlans'],
    })
    const wrapper = await mountView({ rows: [row] })

    const lines = wrapper.findAll('.roles-cell .role-line')
    expect(lines.map((l) => l.text())).toEqual(['eth0: Передача данных · trunk · VLAN 10, 20', 'gi0/1: Передача данных · access · VLAN 10'])
    const diffTexts = wrapper.findAll('.roles-cell .diff').map((d) => d.text())
    expect(diffTexts).toEqual(['trunk', 'VLAN 10, 20', 'access', 'VLAN 10']) // роль совпадает — не выделена
    expect(wrapper.find('.port-badge').text()).toBe('Расхождение (режим, VLAN) — проверить')
  })

  it('одобренное расхождение остаётся с бейджем «Одобрено» и перечнем граней', async () => {
    const row = connection('conn-a', { port_config_status: 'approved', port_config_diff: ['vlans'], source_vlans: [10], destination_vlans: [20] })
    const wrapper = await mountView({ rows: [row] })

    expect(wrapper.find('.port-badge').text()).toBe('Одобрено (VLAN)')
  })

  it('баннер показывает число расхождений по всему реестру; «Показать» включает фильтр расхождений на сервере', async () => {
    const wrapper = await mountView({ rows: [connectionFixture, mismatched], summary: { mismatch: 42 } })

    expect(wrapper.find('.mismatch-banner').text()).toContain('42')

    await wrapper.find('[data-action="show-mismatches"]').trigger('click')
    await flushPromises()

    expect(lastPageParams().get('port_config_status')).toBe('mismatch')
    expect(wrapper.find('[data-action="show-mismatches"]').exists()).toBe(false)
  })

  it('строка с расхождением показывает роли обоих портов и метку «Расхождение», одобренная — «Одобрено»', async () => {
    const wrapper = await mountView({ rows: [mismatched, approved] })

    const [mismatchRow, approvedRow] = rowsText(wrapper)
    expect(mismatchRow).toContain('idrac: Управление активами')
    expect(mismatchRow).toContain('gi0/7: Передача данных')
    expect(mismatchRow).toContain('Расхождение')
    expect(approvedRow).toContain('Одобрено')
  })

  it('фильтры «Расхождения (N)» и «Одобренные (N)» показывают счётчики сервера и запрашивают нужный статус', async () => {
    const wrapper = await mountView({ rows: [connectionFixture], summary: { mismatch: 42, approved: 7 } })

    expect(wrapper.find('[data-filter="mismatch"]').text()).toContain('(42)')
    expect(wrapper.find('[data-filter="approved"]').text()).toContain('(7)')

    await wrapper.find('[data-filter="approved"]').trigger('click')
    await flushPromises()
    expect(lastPageParams().get('port_config_status')).toBe('approved')

    await wrapper.find('[data-filter="mismatch"]').trigger('click')
    await flushPromises()
    expect(lastPageParams().get('port_config_status')).toBe('mismatch')
  })

  it('клик по метке расхождения открывает окно проверки этого подключения', async () => {
    const wrapper = await mountView({ rows: [mismatched] })

    await wrapper.find('.port-badge').trigger('click')

    const modal = wrapper.findComponent(PortConfigReviewModal)
    expect(modal.exists()).toBe(true)
    expect(modal.text()).toContain('srv-02')
    modal.vm.$emit('close')
    await flushPromises()
    expect(wrapper.findComponent(PortConfigReviewModal).exists()).toBe(false)
  })

  describe('«Одобрить все найденные»', () => {
    async function withMismatchFilter(options: ServerOptions) {
      const wrapper = await mountView(options)
      await wrapper.find('[data-filter="mismatch"]').trigger('click')
      await flushPromises()
      return wrapper
    }

    it('кнопка видна только при фильтре расхождений и показывает число ВСЕХ найденных, а не строк на странице', async () => {
      const wrapper = await mountView({ rows: [mismatched], total: 12 })
      expect(wrapper.find('[data-action="approve-all"]').exists()).toBe(false)

      await wrapper.find('[data-filter="mismatch"]').trigger('click')
      await flushPromises()

      expect(wrapper.find('[data-action="approve-all"]').text()).toContain('(12)')
    })

    it('кнопки нет, если под фильтром ничего не найдено', async () => {
      const wrapper = await withMismatchFilter({ rows: [], total: 0 })
      expect(wrapper.find('[data-action="approve-all"]').exists()).toBe(false)
    })

    it('после подтверждения отправляет на сервер условия поиска (а не id со страницы) и перечитывает страницу', async () => {
      const confirmMock = vi.fn(() => true)
      vi.stubGlobal('confirm', confirmMock)
      const wrapper = await withMismatchFilter({ rows: [mismatched], total: 12 })
      const before = pageRequests().length

      await wrapper.find('[data-action="approve-all"]').trigger('click')
      await flushPromises()

      expect(confirmMock).toHaveBeenCalledWith(expect.stringContaining('12'))
      expect(approveRequests()).toHaveLength(1)
      expect(approveRequests()[0].body).toEqual({ match: { q: null, is_active: null } })
      expect(pageRequests().length).toBeGreaterThan(before)
    })

    it('условия поиска и активности попадают в запрос одобрения', async () => {
      vi.stubGlobal('confirm', vi.fn(() => true))
      const wrapper = await withMismatchFilter({ rows: [mismatched], total: 3 })
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      await wrapper.find('.search-box input').setValue('ядро')
      vi.advanceTimersByTime(300)
      await flushPromises()
      vi.useRealTimers()

      await wrapper.find('[data-action="approve-all"]').trigger('click')
      await flushPromises()

      expect(approveRequests().at(-1)!.body).toEqual({ match: { q: 'ядро', is_active: null } })
    })

    it('ничего не отправляет, если пользователь отказался в подтверждении', async () => {
      vi.stubGlobal('confirm', vi.fn(() => false))
      const wrapper = await withMismatchFilter({ rows: [mismatched], total: 12 })

      await wrapper.find('[data-action="approve-all"]').trigger('click')
      await flushPromises()

      expect(approveRequests()).toEqual([])
    })
  })
})

describe('ConnectionsView.vue — согласование портов по правилам', () => {
  const syncPlan = {
    items: [],
    summary: { connections: 0, applicable: 0, shown: 0, total_items: 0, auto: 0, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0 },
    plan_hash: 'h',
  }
  const syncCalls = (suffix: string) => calls.filter((c) => c.method === 'POST' && c.url.endsWith(suffix))

  it('кнопка «Согласовать по правилам…» видна только при наличии расхождений в реестре', async () => {
    const withMismatch = await mountView({ rows: [connection('c-1', { port_config_status: 'mismatch', port_config_diff: ['role'] })] })
    expect(withMismatch.find('[data-action="sync-by-rules"]').exists()).toBe(true)

    const clean = await mountView({ rows: [connection('c-2')] })
    expect(clean.find('[data-action="sync-by-rules"]').exists()).toBe(false)
  })

  it('кнопка видна, даже если текущий фильтр скрыл все расхождения: счётчик — по всему реестру', async () => {
    const wrapper = await mountView({ rows: [], summary: { mismatch: 3 } })

    expect(wrapper.find('[data-action="sync-by-rules"]').exists()).toBe(true)
  })

  it('открывает план по всем подключениям с расхождением (без списка), а применение перечитывает страницу', async () => {
    const wrapper = await mountView({
      rows: [connection('c-1', { port_config_status: 'mismatch', port_config_diff: ['role'] })],
      extra: (call) => {
        if (call.method === 'POST' && call.url.endsWith('/port-sync/preview')) {
          return jsonResponse({ ...syncPlan, summary: { ...syncPlan.summary, connections: 1, applicable: 1, auto: 1 }, items: [] })
        }
        if (call.method === 'POST' && call.url.endsWith('/port-sync/apply')) {
          return jsonResponse({ applied: { ports: 1, connections: 1 }, connection_ids: ['c-1'], summary: syncPlan.summary })
        }
        return undefined
      },
    })
    const pagesBefore = pageRequests().length

    await wrapper.find('[data-action="sync-by-rules"]').trigger('click')
    await flushPromises()
    expect(syncCalls('/port-sync/preview')[0].body).toEqual({})
    expect(wrapper.text()).toContain('Согласование портов по правилам')

    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()

    expect(syncCalls('/port-sync/apply')[0].body).toEqual({ plan_hash: 'h', confirm: true })
    expect(pageRequests().length).toBeGreaterThan(pagesBefore)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
