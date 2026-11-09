import { describe, it, expect } from 'vitest'
import { routes } from '../../router'
import { PAGE_TITLES, resolvePageHeading } from '../pageTitles'

describe('pageTitles — заголовки верхней панели', () => {
  it('у каждого именованного маршрута (кроме входа) есть читаемый заголовок, а не техническое имя маршрута', () => {
    const names = routes.map((r) => r.name).filter((name): name is string => typeof name === 'string' && name !== 'login')

    expect(names.length).toBeGreaterThan(0)
    for (const name of names) {
      const heading = PAGE_TITLES[name]
      expect(heading, `нет заголовка для маршрута «${name}»`).toBeDefined()
      expect(heading.title).not.toBe(name)
      expect(heading.title.trim()).not.toBe('')
    }
  })

  it.each([
    ['device-stacks', 'Стеки устройств'],
    ['diagrams', 'Диаграмма топологии сети'],
    ['diagram-detail', 'Диаграмма топологии сети'],
    ['containers', 'Контейнеры'],
    ['other-catalogs', 'Другие справочники'],
  ])('маршрут «%s» получает заголовок «%s»', (routeName, title) => {
    expect(resolvePageHeading(routeName).title).toBe(title)
  })

  // F-08 (код-ревью main): в крошках стояло «Лист 1 · …» — номер листа Excel-отчёта, который в интерфейсе никому ничего не говорит, а у
  // экранов одной группы префиксы расходились («Инвентаризация ›» у устройств и стеков, «Лист N ·» у остальных).
  it('F-08: в крошках нет номеров листов отчёта', () => {
    for (const [name, heading] of Object.entries(PAGE_TITLES)) {
      expect(heading.crumb, `крошка маршрута «${name}»`).not.toMatch(/Лист\s*\d/i)
    }
  })

  it.each([
    ['information-systems', 'Информационные системы'],
    ['devices', 'Физические устройства'],
    ['device-stacks', 'Стеки устройств'],
    ['connections', 'Подключения'],
    ['vms', 'Виртуальные машины'],
    ['containers', 'Контейнеры'],
  ])('F-08: крошка экрана «%s» — «Реестр › %s», как название группы меню', (routeName, screen) => {
    expect(PAGE_TITLES[routeName].crumb).toBe(`Реестр › ${screen}`)
  })

  it('для неизвестного маршрута берётся meta.title, а без него — само имя (панель не остаётся пустой)', () => {
    expect(resolvePageHeading('unknown-route', 'Свой заголовок')).toEqual({ title: 'Свой заголовок', crumb: '' })
    expect(resolvePageHeading('unknown-route')).toEqual({ title: 'unknown-route', crumb: '' })
    expect(resolvePageHeading(undefined)).toEqual({ title: '', crumb: '' })
  })
})
