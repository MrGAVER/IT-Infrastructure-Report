import { expect, test } from '@playwright/test'
import { findEmptyIcons, observePage, openApp } from './fixtures.ts'

// Обход всех экранов без параметров (17 маршрутов; редакторы шаблонов и диаграмма по id требуют данных) на трёх размерах окна.
// На каждом экране: страница не шире окна (нет горизонтальной прокрутки), нет ошибок в консоли и неудачных запросов, нет запросов
// к чужим хостам, все видимые иконки спрайта нарисованы. Проверки данных-зависимой вёрстки (таблицы с записями) — отдельно, на
// заполненной базе: чистая база показывает только пустые состояния.
const ROUTES = [
  '/dashboard',
  '/information-systems',
  '/devices',
  '/device-stacks',
  '/connections',
  '/vms',
  '/containers',
  '/vlans',
  '/buildings',
  '/structural-units',
  '/other-catalogs',
  '/reports',
  '/report-templates',
  '/diagrams',
  '/port-sync-rules',
  '/audit-log',
  '/settings',
]

const VIEWPORTS = [
  { name: 'телефон 390×667', width: 390, height: 667 },
  { name: 'планшет 820×1180', width: 820, height: 1180 },
  { name: 'десктоп 1440×900', width: 1440, height: 900 },
]

for (const viewport of VIEWPORTS) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const route of ROUTES) {
      test(`${route}: без горизонтальной прокрутки, ошибок, внешних запросов и пустых иконок`, async ({ page, baseURL }) => {
        const observation = observePage(page, baseURL ?? '')
        await openApp(page, route)

        const { scrollWidth, innerWidth } = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }))
        expect(scrollWidth, 'страница шире окна — появилась горизонтальная прокрутка').toBeLessThanOrEqual(innerWidth)
        // Прокручивается именно .content, а не документ: элемент, выступающий за правый край, document.scrollWidth не раздувает
        // (так на телефоне выходила за край кнопка «Новая диаграмма» — UI-4, критерий «ни один элемент не выходит за правый край»).
        const contentOverflow = await page.evaluate(() => {
          const content = document.querySelector('.content')
          return content ? content.scrollWidth - content.clientWidth : 0
        })
        expect(contentOverflow, 'область .content шире окна — что-то выходит за правый край').toBeLessThanOrEqual(0)
        expect(observation.pageErrors).toEqual([])
        expect(observation.consoleErrors).toEqual([])
        expect(observation.failedRequests).toEqual([])
        expect(observation.foreignRequests).toEqual([])
        expect(await findEmptyIcons(page)).toEqual([])
      })
    }
  })
}
