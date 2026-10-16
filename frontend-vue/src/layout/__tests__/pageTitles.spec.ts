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

  it('для неизвестного маршрута берётся meta.title, а без него — само имя (панель не остаётся пустой)', () => {
    expect(resolvePageHeading('unknown-route', 'Свой заголовок')).toEqual({ title: 'Свой заголовок', crumb: '' })
    expect(resolvePageHeading('unknown-route')).toEqual({ title: 'unknown-route', crumb: '' })
    expect(resolvePageHeading(undefined)).toEqual({ title: '', crumb: '' })
  })
})
