import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ReportReadinessCard from '../ReportReadinessCard.vue'
import type { ReportReadiness } from '../../api/consistency'
import { READINESS, UNCHECKED_SHEET, readinessOf, sheetReadiness } from '../../__tests__/consistencyFixtures'

function stubServer(body: () => Response | ReportReadiness) {
  const fetchMock = vi.fn(async () => {
    const answer = body()
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountCard() {
  const wrapper = mount(ReportReadinessCard)
  await flushPromises()
  return wrapper
}

const sheet = (wrapper: Awaited<ReturnType<typeof mountCard>>, number: number) => wrapper.find(`[data-sheet="${number}"]`)

describe('ReportReadinessCard', () => {
  it('показывает заголовок и по строке на каждый лист отчёта', async () => {
    stubServer(() => READINESS)
    const wrapper = await mountCard()

    expect(wrapper.find('h2').text()).toBe('Готовность отчёта')
    expect(wrapper.findAll('.sheet').map((item) => item.find('.sheet-title').text())).toEqual([
      'Лист 1 — Информационные системы',
      'Лист 2 — Физические устройства',
      'Лист 3 — Подключения',
      'Лист 4 — Виртуальные машины и контейнеры',
    ])
  })

  it('у проверенного листа — процент, шкала с доступным значением и «готовы N из M»', async () => {
    stubServer(() => READINESS)
    const wrapper = await mountCard()
    const second = sheet(wrapper, 2)

    expect(second.find('.percent').text()).toBe('94 %')
    expect(second.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('94')
    expect(second.find('.fill').attributes('style')).toContain('width: 94%')
    expect(second.find('.meta').text()).toContain('Готовы 32 из 34')
    expect(second.find('.meta').text()).toContain('3 проблемы')
  })

  it('«Показать» ведёт на экран проверки с этим листом', async () => {
    stubServer(() => READINESS)
    const wrapper = await mountCard()

    expect(sheet(wrapper, 1).find('.show-link').attributes('href')).toBe('/consistency?sheet=1')
    expect(sheet(wrapper, 2).find('.show-link').attributes('href')).toBe('/consistency?sheet=2')
  })

  it('лист без проверок не получает ни процента, ни шкалы, ни слов «готово» — только пояснение', async () => {
    stubServer(() => readinessOf([UNCHECKED_SHEET]))
    const wrapper = await mountCard()
    const third = sheet(wrapper, 3)

    expect(third.find('.percent').exists()).toBe(false)
    expect(third.find('[role="progressbar"]').exists()).toBe(false)
    expect(third.text()).toContain('Проверки для этого листа пока не реализованы')
    expect(third.text()).toContain('Объектов на листе: 91')
  })

  it('лист подключений проверяется: процент, шкала и частая проблема', async () => {
    stubServer(() => READINESS)
    const wrapper = await mountCard()
    const third = sheet(wrapper, 3)

    expect(third.find('.percent').text()).toBe('94 %')
    expect(third.find('.top-rules').text()).toContain('У подключения не указано назначение линии связи (5)')
    expect(third.find('.show-link').attributes('href')).toBe('/consistency?sheet=3')
  })

  it('когда готовы все объекты — 100 %, «Все объекты готовы» и отметка выполнения, без ссылки «Показать»', async () => {
    stubServer(() => READINESS)
    const wrapper = await mountCard()
    const fourth = sheet(wrapper, 4)

    expect(fourth.find('.percent').text()).toBe('100 %')
    expect(fourth.find('.percent').classes()).toContain('done')
    expect(fourth.find('.fill').classes()).toContain('done')
    expect(fourth.find('.meta').text()).toContain('Все объекты готовы (134)')
    expect(fourth.find('.show-link').exists()).toBe(false)
  })

  it('99 % — это ещё не «готово»: отметки выполнения нет', async () => {
    stubServer(() => readinessOf([sheetReadiness({ total: 300, affected: 1, ready: 299, percent: 99 })]))
    const wrapper = await mountCard()

    expect(wrapper.find('.percent').text()).toBe('99 %')
    expect(wrapper.find('.percent').classes()).not.toContain('done')
    expect(wrapper.find('.meta').text()).not.toContain('Все объекты готовы')
  })

  it('лист без объектов — «нет объектов», а не 0 % и не 100 %', async () => {
    stubServer(() => readinessOf([sheetReadiness({ total: 0, affected: 0, ready: 0, percent: null, problems: 0 })]))
    const wrapper = await mountCard()

    expect(wrapper.find('.percent').exists()).toBe(false)
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('На листе пока нет объектов')
  })

  it.each([
    [1, '1 проблема'],
    [2, '2 проблемы'],
    [5, '5 проблем'],
    [21, '21 проблема'],
  ])('число проблем склоняется: %i → «%s»', async (problems, text) => {
    stubServer(() => readinessOf([sheetReadiness({ problems })]))
    const wrapper = await mountCard()

    expect(wrapper.find('.meta').text()).toContain(text)
  })

  it('показывает, чего не хватает чаще всего, и сколько проблем одобрено', async () => {
    stubServer(() =>
      readinessOf([
        sheetReadiness({
          approved: 2,
          top_rules: [
            { rule: 'a', title: 'Нет здания', count: 2 },
            { rule: 'b', title: 'Нет модели', count: 1 },
          ],
        }),
      ]),
    )
    const wrapper = await mountCard()

    expect(wrapper.find('.top-rules').text()).toBe('Чаще всего: Нет здания (2); Нет модели (1)')
    expect(wrapper.find('.meta').text()).toContain('одобрено: 2')
  })

  it('проблемы без листа выведены отдельной строкой со ссылкой; при нуле строки нет', async () => {
    stubServer(() => READINESS)
    const withUnassigned = await mountCard()
    expect(withUnassigned.find('.unassigned').text()).toContain('Ещё 2 проблемы не привязаны к листу')
    expect(withUnassigned.find('.unassigned a').attributes('href')).toBe('/consistency')

    stubServer(() => readinessOf(READINESS.sheets, 0))
    expect((await mountCard()).find('.unassigned').exists()).toBe(false)
  })

  it('пока данные не пришли — «Считаем готовность…», без чисел', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )
    const wrapper = mount(ReportReadinessCard)
    await flushPromises()

    expect(wrapper.find('.loading').text()).toBe('Считаем готовность…')
    expect(wrapper.find('.sheet').exists()).toBe(false)
  })

  it('ошибка сервера не выглядит как «отчёт готов»: причина и «Повторить», который читает данные заново', async () => {
    let failing = true
    const fetchMock = stubServer(() => (failing ? new Response(JSON.stringify({ detail: 'База недоступна' }), { status: 500 }) : READINESS))
    const wrapper = await mountCard()

    expect(wrapper.find('[role="alert"]').text()).toContain('Не удалось посчитать готовность')
    expect(wrapper.find('.sheet').exists()).toBe(false)

    failing = false
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('.sheet')).toHaveLength(4)
  })
})
