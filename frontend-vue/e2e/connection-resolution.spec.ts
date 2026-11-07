import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { cleanupSeeded, seedMismatchedConnection } from './seed.ts'

// FE-08 (ревью ветки fix/code-review-main-f06-stage2-f05): панель «Расхождение конфигурации портов» показывается вместо кнопок «Отмена /
// Сохранить». Нажатая кнопка уходит из DOM, и фокус терялся на <body>; сама панель называлась alertdialog, но фокус не переносила.
// Проверка идёт в настоящем браузере: jsdom не воспроизводит, куда браузер девает фокус при удалении сфокусированного элемента.

test.afterEach(async ({ request }) => {
  await cleanupSeeded(request)
})

async function openMismatchedConnection(page: import('@playwright/test').Page, request: import('@playwright/test').APIRequestContext) {
  const { sourceName } = await seedMismatchedConnection(request)
  await openApp(page, '/connections')
  await page.locator('tr', { hasText: sourceName }).getByRole('button', { name: 'Редактировать' }).click()
  await expect(page.locator('.modal')).toHaveCount(1)
}

test('FE-08: после «Сохранить» фокус переходит в панель расхождения, а «Вернуться к правке» возвращает его на «Сохранить»', async ({ page, request }) => {
  await openMismatchedConnection(page, request)
  const save = page.locator('.modal-foot').getByRole('button', { name: 'Сохранить' })
  await save.focus()
  await page.keyboard.press('Enter')

  const panel = page.getByRole('group', { name: 'Расхождение конфигурации портов' })
  await expect(panel).toBeVisible()
  // Фокус не потерян на <body>: он на первой кнопке решения внутри панели.
  await expect(panel.getByRole('button').first()).toBeFocused()
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe('BODY')

  await panel.getByRole('button', { name: 'Вернуться к правке' }).click()
  await expect(panel).toHaveCount(0)
  await expect(page.locator('.modal-foot').getByRole('button', { name: 'Сохранить' })).toBeFocused()
})
