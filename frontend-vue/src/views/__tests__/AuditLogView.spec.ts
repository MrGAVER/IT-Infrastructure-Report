import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditLogView from '../AuditLogView.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useAuditLogStore } from '../../stores/auditLog'
import { auditJournal, auditServer } from '../../stores/__tests__/fixtures'

let urls: string[]
const pageUrls = () => urls.filter((u) => /\/api\/v1\/audit-log\?/.test(u))
const lastParams = () => new URL(pageUrls().at(-1)!, 'http://x').searchParams

async function mountView(count: number, { fail = false } = {}) {
  urls = []
  const server = auditServer(auditJournal(count))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      urls.push(url)
      if (fail) return new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })
      return new Response(JSON.stringify(server(url)))
    }),
  )
  useCatalogsStore().loaded = true
  const wrapper = mount(AuditLogView)
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountView>>
const pageLabels = (w: Wrapper) => w.findAll('.pager button[aria-label^="Страница"]').map((b) => b.text())
const rows = (w: Wrapper) => w.findAll('tbody tr')
const stats = (w: Wrapper) => w.findAll('.stat-card .num').map((n) => n.text())
const foot = (w: Wrapper) => w.find('.table-foot').text()

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AuditLogView.vue — пагинация', () => {
  it('при большом числе записей номера страниц собираются в окно, а не растягиваются на всю ширину', async () => {
    const wrapper = await mountView(1000) // 12 на странице → 84 страницы

    expect(pageLabels(wrapper)).toEqual(['1', '2', '84'])
    expect(wrapper.findAll('.pager button').length).toBeLessThan(10)
    expect(wrapper.find('.pager-gap').exists()).toBe(true)
    expect(rows(wrapper)).toHaveLength(12)
    expect(foot(wrapper)).toContain('Показано 1–12 из 1000')
  })

  it('на страницу приходит только нужный кусок журнала: клиент не держит все записи', async () => {
    const wrapper = await mountView(1000)

    expect(pageUrls()).toHaveLength(1)
    expect(lastParams().get('limit')).toBe('12')
    expect(useAuditLogStore().items).toHaveLength(12)
    expect(rows(wrapper)).toHaveLength(12)
  })

  it('переход на последнюю страницу запрашивает её у сервера; окно номеров следует за страницей', async () => {
    const wrapper = await mountView(1000)

    await wrapper.find('.pager button[aria-label="Страница 84"]').trigger('click')
    await flushPromises()

    expect(lastParams().get('offset')).toBe('996')
    expect(pageLabels(wrapper)).toEqual(['1', '83', '84'])
    expect(rows(wrapper)).toHaveLength(4) // 1000 = 83·12 + 4
    expect(foot(wrapper)).toContain('Показано 997–1000 из 1000')
  })

  it('«›» и «‹» листают по одной странице', async () => {
    const wrapper = await mountView(100)

    await wrapper.find('.pager button[aria-label="Следующая страница"]').trigger('click')
    await flushPromises()
    expect(useAuditLogStore().page).toBe(2)
    expect(lastParams().get('offset')).toBe('12')

    await wrapper.find('.pager button[aria-label="Предыдущая страница"]').trigger('click')
    await flushPromises()
    expect(useAuditLogStore().page).toBe(1)
  })

  it('записи старше первой тысячи доступны: журнал в 2500 записей листается до самой старой', async () => {
    const wrapper = await mountView(2500)

    await wrapper.find(`.pager button[aria-label="Страница ${Math.ceil(2500 / 12)}"]`).trigger('click')
    await flushPromises()

    expect(foot(wrapper)).toContain('из 2500')
    expect(rows(wrapper).at(-1)!.text()).toContain('Запись 2499')
  })

  it('одна страница записей — пейджер из одной кнопки, а не пустая полоса', async () => {
    const wrapper = await mountView(5)

    expect(pageLabels(wrapper)).toEqual(['1'])
  })

  it('пустой журнал: сообщение «Ничего не найдено», 0–0 из 0', async () => {
    const wrapper = await mountView(0)

    expect(wrapper.text()).toContain('Ничего не найдено по заданным фильтрам.')
    expect(foot(wrapper)).toContain('Показано 0–0 из 0')
  })
})

describe('AuditLogView.vue — счётчики и размер страницы', () => {
  it('счётчики — по всему журналу и не меняются от поиска и фильтров', async () => {
    const wrapper = await mountView(100)
    expect(stats(wrapper)).toEqual(['100', '34', '33', '33'])

    await wrapper.findAll('.chip-group button').find((b) => b.text() === 'Удаление')!.trigger('click')
    await flushPromises()

    expect(lastParams().get('action')).toBe('DELETE')
    expect(foot(wrapper)).toContain('из 33')
    expect(stats(wrapper)).toEqual(['100', '34', '33', '33'])
  })

  it('выбор «Показывать по N» запрашивает страницу с новым limit и пересчитывает диапазон и пейджер', async () => {
    const wrapper = await mountView(1000)

    await wrapper.find('.table-foot select').setValue('48')
    await flushPromises()

    expect(lastParams().get('limit')).toBe('48')
    expect(rows(wrapper)).toHaveLength(48)
    expect(foot(wrapper)).toContain('Показано 1–48 из 1000')
    expect(pageLabels(wrapper)).toEqual(['1', '2', '21'])
  })

  it('размер страницы запоминается между открытиями экрана', async () => {
    const first = await mountView(100)
    await first.find('.table-foot select').setValue('24')
    await flushPromises()
    first.unmount()

    setActivePinia(createPinia()) // «перезагрузка»: стор создаётся заново и читает localStorage
    const second = await mountView(100)

    expect(lastParams().get('limit')).toBe('24')
    expect(rows(second)).toHaveLength(24)
  })

  it('фильтр «Раздел» наполняется разделами из журнала, а не всеми ресурсами', async () => {
    const wrapper = await mountView(100)

    const options = wrapper.findAll('select.fbtn option').map((o) => o.attributes('value'))

    expect(options).toEqual(['', 'devices', 'vms'])
  })
})

describe('AuditLogView.vue — поиск и фильтры на сервере', () => {
  // Только setTimeout/clearTimeout: flushPromises() использует setImmediate, который нельзя подменять.
  const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

  it('запрос поиска уходит после паузы в наборе — одним запросом на серию нажатий — и с первой страницы', async () => {
    const wrapper = await mountView(1000)
    await wrapper.find('.pager button[aria-label="Страница 2"]').trigger('click')
    await flushPromises()
    fakeTimers()
    const before = pageUrls().length

    const input = wrapper.find('.search-box input')
    await input.setValue('З')
    await input.setValue('Зап')
    await input.setValue('Запись 99')
    vi.advanceTimersByTime(299)
    expect(pageUrls().length).toBe(before)
    vi.advanceTimersByTime(1)
    await flushPromises()

    expect(pageUrls().length).toBe(before + 1)
    expect(lastParams().get('q')).toBe('Запись 99')
    expect(lastParams().get('offset')).toBe('0')
    expect(useAuditLogStore().page).toBe(1)
    expect(foot(wrapper)).toContain('из 11') // «Запись 99», 990–999 и 99
  })

  it('поиск находит запись из давней части журнала, которой не было бы среди последних записей', async () => {
    const wrapper = await mountView(2500)
    fakeTimers()

    await wrapper.find('.search-box input').setValue('Запись 2499')
    vi.advanceTimersByTime(300)
    await flushPromises()

    expect(rows(wrapper)).toHaveLength(1)
    expect(rows(wrapper)[0].text()).toContain('Запись 2499')
  })

  it('смена фильтра уходит сразу и отменяет ещё не отправленный поиск (без лишнего запроса со старой строкой)', async () => {
    const wrapper = await mountView(100)
    fakeTimers()
    const before = pageUrls().length

    await wrapper.find('.search-box input').setValue('Запись')
    await wrapper.findAll('.chip-group button').find((b) => b.text() === 'Создание')!.trigger('click')
    await flushPromises()

    expect(pageUrls().length).toBe(before + 1)
    expect(lastParams().get('action')).toBe('CREATE')
    vi.advanceTimersByTime(1000)
    await flushPromises()
    expect(pageUrls().length).toBe(before + 1)
  })

  it('фильтр «Раздел» передаётся серверу', async () => {
    const wrapper = await mountView(100)

    await wrapper.find('select.fbtn').setValue('vms')
    await flushPromises()

    expect(lastParams().get('entity_type')).toBe('vms')
    expect(foot(wrapper)).toContain('из 25')
  })

  it('после закрытия экрана неотправленный поиск не уходит', async () => {
    const wrapper = await mountView(100)
    fakeTimers()
    const before = pageUrls().length

    await wrapper.find('.search-box input').setValue('Запись')
    wrapper.unmount()
    vi.advanceTimersByTime(1000)
    await flushPromises()

    expect(pageUrls().length).toBe(before)
  })
})

describe('AuditLogView.vue — загрузка и ошибки', () => {
  it('при каждом открытии экрана читается актуальная страница, а не кэш', async () => {
    const first = await mountView(100)
    first.unmount()

    const second = await mountView(100)

    expect(pageUrls()).toHaveLength(1) // urls сбрасывается в mountView: запрос ушёл и при втором открытии
    expect(rows(second)).toHaveLength(12)
  })

  it('«Обновить» перечитывает текущую страницу', async () => {
    const wrapper = await mountView(100)
    await wrapper.find('.pager button[aria-label="Страница 2"]').trigger('click')
    await flushPromises()
    const before = pageUrls().length

    await wrapper.findAll('.filter-bar .btn').find((b) => b.text().includes('Обновить'))!.trigger('click')
    await flushPromises()

    expect(pageUrls().length).toBe(before + 1)
    expect(lastParams().get('offset')).toBe('12')
    expect(useAuditLogStore().page).toBe(2)
  })

  it('ошибка сервера показывается баннером', async () => {
    const wrapper = await mountView(100, { fail: true })

    expect(wrapper.find('.error-banner').text()).toContain('Сервер недоступен')
    expect(rows(wrapper)).toHaveLength(0)
  })
})

describe('AuditLogView.vue — автор действия', () => {
  it('показывает пользователя в отдельной колонке, адрес — во всплывающей подсказке', async () => {
    const wrapper = await mountView(10)

    expect(wrapper.findAll('thead th').map((th) => th.text())).toContain('Пользователь')
    const cells = wrapper.findAll('tbody td.actor-cell')
    expect(cells).toHaveLength(10)
    expect(cells[1].text()).toBe('admin')
    expect(cells[1].attributes('title')).toBe('IP-адрес: 10.0.0.7')
  })

  it('у записи без автора (сделана до появления колонки) вместо имени — прочерк', async () => {
    const wrapper = await mountView(10)

    const first = wrapper.findAll('tbody td.actor-cell')[0]
    expect(first.text()).toBe('—')
    expect(first.attributes('title')).toBeUndefined()
  })
})
