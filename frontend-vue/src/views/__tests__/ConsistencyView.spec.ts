// Экран «Проверка данных»: находки сервера, фильтры, пустые состояния, ошибка загрузки, страницы.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ConsistencyView from '../ConsistencyView.vue'
import type { ConsistencyReport } from '../../api/consistency'
import { finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'

let calls: string[]

/** Сервер проверок: отчёт и каталог правил. `report` — функция, чтобы тест мог менять ответ между запросами. */
function stubServer(report: () => Response | ConsistencyReport) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      if (url.endsWith('/consistency/rules')) return new Response(JSON.stringify({ rules: RULES }))
      const body = report()
      return body instanceof Response ? body : new Response(JSON.stringify(body))
    }),
  )
}

async function mountView() {
  const wrapper = mount(ConsistencyView)
  await flushPromises()
  return wrapper
}

const rows = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.findAll('tbody tr').filter((row) => !row.find('[data-empty]').exists())

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
})

describe('ConsistencyView', () => {
  it('показывает счётчики по важности и по строке на каждую находку', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()

    const cards = wrapper.findAll('.stat-card').map((card) => card.text())
    expect(cards).toEqual(['3Всего находок', '1Ошибки', '2Предупреждения', '0Сведения'])
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

  it('имя ВМ ведёт в раздел «Виртуальные машины», а у IP-адреса ссылки нет', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()

    const links = wrapper.findAll('tbody a').map((link) => [link.text(), link.attributes('href')])
    expect(links).toEqual([
      ['vm-1', '/vms'],
      ['orphan', '/vms'],
    ])
  })

  it('чип важности и поиск сужают список, «Все» возвращает его', async () => {
    stubServer(() => reportOf(MIXED))
    const wrapper = await mountView()

    await wrapper
      .findAll('.chip-group button')
      .find((button) => button.text() === 'Ошибка')!
      .trigger('click')
    expect(rows(wrapper)).toHaveLength(1)

    await wrapper
      .findAll('.chip-group button')
      .find((button) => button.text() === 'Все')!
      .trigger('click')
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
