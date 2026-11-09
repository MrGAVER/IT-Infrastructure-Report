import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'

// F-05 (код-ревью main): подсказка о горизонтальной прокрутке таблицы (затухание края + tabindex) была только у устройств,
// подключений и ИС. Журнал аудита, шаблоны отчётов, «Другие справочники», виртуальные машины и контейнеры на телефоне
// прокручивались вбок без всякого признака, а кнопки «Изменить» и «Удалить» лежат в последней колонке — за краем экрана.
//
// Данные не нужны: у этих таблиц есть минимальная ширина (760–820 px), поэтому на телефоне они переполняются и с пустым
// состоянием, а «Другие справочники» с первого же справочника показывают записи, заведённые миграциями.
const TABLES = [
  { route: '/audit-log', name: 'журнал аудита' },
  { route: '/report-templates', name: 'шаблоны отчётов' },
  { route: '/other-catalogs', name: 'другие справочники' },
  { route: '/vms', name: 'виртуальные машины' },
  { route: '/containers', name: 'контейнеры' },
]

test.describe('телефон 390×844: подсказка прокрутки у таблиц', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const { route, name } of TABLES) {
    test(`F-05: ${name} (${route}) — затухает правый край, контейнер в порядке фокуса; после прокрутки до конца — левый`, async ({ page }) => {
      await openApp(page, route)

      const wrap = page.locator('.table-wrap')
      await expect(wrap).toHaveCount(1)
      await expect(wrap).toHaveAttribute('role', 'region')
      await expect(wrap).toHaveClass(/shade-right/)
      await expect(wrap).not.toHaveClass(/shade-left/)
      await expect(wrap).toHaveAttribute('tabindex', '0')

      await wrap.evaluate((el) => {
        el.scrollLeft = el.scrollWidth
      })
      await expect(wrap).toHaveClass(/shade-left/)
      await expect(wrap).not.toHaveClass(/shade-right/)
    })
  }
})

// Подсказка не должна врать при любой ширине окна: тень и tabindex есть тогда и только тогда, когда таблица действительно шире
// окна. Факт переполнения измеряется, а не предполагается — «впритык» он зависит от версии Chromium и растеризации шрифта.
for (const viewport of [
  { name: 'телефон 390', width: 390, height: 844 },
  { name: 'планшет 820', width: 820, height: 1180 },
  { name: 'десктоп 1440', width: 1440, height: 900 },
]) {
  test.describe(`${viewport.name}: подсказка совпадает с фактом переполнения`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const { route, name } of TABLES) {
      test(`F-05: ${name} (${route})`, async ({ page }) => {
        await openApp(page, route)

        const wrap = page.locator('.table-wrap')
        const scrollable = await wrap.evaluate((el) => el.scrollWidth > el.clientWidth)
        if (scrollable) {
          await expect(wrap).toHaveClass(/shade-right/)
          await expect(wrap).toHaveAttribute('tabindex', '0')
        } else {
          await expect(wrap).not.toHaveClass(/shade-(left|right)/)
          await expect(wrap).not.toHaveAttribute('tabindex', /.*/)
        }
      })
    }
  })
}
