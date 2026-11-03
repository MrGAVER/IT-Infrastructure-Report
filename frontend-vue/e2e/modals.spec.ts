import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'

// Модальные окна (ревью 2.158.0, UI-04): закрытие по Esc, доступное имя диалога, кнопки действий длинной формы всегда на экране.
// Проверяется форма устройства: самая длинная в приложении (1373 px при окне 900 и 2010 px при 667) и с вложенными окнами «+».

const OPEN_FORM = async (page: import('@playwright/test').Page) => {
  await openApp(page, '/devices')
  await page.getByRole('button', { name: 'Добавить устройство' }).click()
  await expect(page.locator('.modal')).toHaveCount(1)
}

test.describe('UI-04: модальные окна', () => {
  test('Esc закрывает окно', async ({ page }) => {
    await OPEN_FORM(page)
    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(0)
  })

  test('при вложенных окнах Esc закрывает только верхнее', async ({ page }) => {
    await OPEN_FORM(page)
    await page.locator('.modal .quick-add-btn').first().click()
    await expect(page.locator('.modal')).toHaveCount(2)

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(1)
    await expect(page.getByRole('dialog', { name: 'Добавить устройство' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(0)
  })

  test('Esc сначала закрывает открытый список выбора, и только следующий — окно', async ({ page }) => {
    await OPEN_FORM(page)
    await page.locator('.modal .searchable-select input').first().click()
    await expect(page.locator('.ss-panel')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.locator('.ss-panel')).toHaveCount(0)
    await expect(page.locator('.modal')).toHaveCount(1)

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(0)
  })

  test('у диалога есть доступное имя — заголовок окна', async ({ page }) => {
    await OPEN_FORM(page)
    await expect(page.getByRole('dialog', { name: 'Добавить устройство' })).toBeVisible()
  })

  test.describe('низкое окно 1440×667', () => {
    test.use({ viewport: { width: 1440, height: 667 } })

    test('кнопки «Отмена» и «Добавить» длинной формы видны без прокрутки', async ({ page }) => {
      await OPEN_FORM(page)
      // Без этого условия тест ничего бы не доказывал: форма обязана быть выше окна.
      const modalHeight = await page.locator('.modal').evaluate((el) => el.getBoundingClientRect().height)
      expect(modalHeight).toBeGreaterThan(667)
      await expect(page.locator('.modal .modal-foot').getByRole('button', { name: 'Отмена' })).toBeInViewport({ ratio: 1 })
      await expect(page.locator('.modal .modal-foot').getByRole('button', { name: 'Добавить' })).toBeInViewport({ ratio: 1 })
    })
  })
})
