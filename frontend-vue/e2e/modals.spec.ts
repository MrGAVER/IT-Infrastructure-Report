import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'

// Модальные окна (ревью 2.158.0, UI-04): закрытие по Esc, доступное имя диалога, кнопки действий длинной формы всегда на экране.
// Проверяется форма устройства: самая длинная в приложении (1373 px при окне 900 и 2010 px при 667) и с вложенными окнами «+».

const OPEN_FORM = async (page: import('@playwright/test').Page) => {
  await openApp(page, '/devices')
  // На пустом реестре такая же кнопка есть и в пустой строке таблицы (F-04, ListEmptyRow); берём кнопку панели — она первая в разметке.
  await page.getByRole('button', { name: 'Добавить устройство' }).first().click()
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

// F-01 (код-ревью main, WCAG 2.4.3 и 2.1.2): раньше после открытия окна активным оставался элемент под подложкой, первый Tab уводил
// фокус на невидимые элементы страницы, а страница под окном прокручивалась. Окна теперь строятся на BaseModal (ловушка фокуса,
// возврат фокуса, блокировка прокрутки, слой по стеку окон); здесь — то, что jsdom проверить не может: настоящий Tab и вёрстка.
test.describe('F-01: фокус и прокрутка модальных окон', () => {
  // Фокус в самом верхнем по стеку окне; для проверки «не ушёл на страницу» достаточно, чтобы он лежал внутри какого-нибудь диалога.
  const focusInDialog = (page: import('@playwright/test').Page) => page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))

  test('после открытия фокус внутри окна, Tab и Shift+Tab не выводят его на страницу', async ({ page }) => {
    await OPEN_FORM(page)
    await expect.poll(() => focusInDialog(page)).toBe(true)

    // Shift+Tab с самого диалога (фокус при открытии) замыкается на последний элемент окна, а не уходит на страницу.
    await page.keyboard.press('Shift+Tab')
    expect(await focusInDialog(page)).toBe(true)

    // Форма длиннее одного прохода: 80 нажатий гарантированно пересекают границу окна в обе стороны.
    for (let i = 0; i < 80; i++) {
      await page.keyboard.press('Tab')
      expect(await focusInDialog(page), `Tab №${i + 1} вывел фокус из окна`).toBe(true)
    }
    for (let i = 0; i < 80; i++) {
      await page.keyboard.press('Shift+Tab')
      expect(await focusInDialog(page), `Shift+Tab №${i + 1} вывел фокус из окна`).toBe(true)
    }
  })

  test('после закрытия фокус возвращается на кнопку, открывшую окно', async ({ page }) => {
    await openApp(page, '/devices')
    const opener = page.getByRole('button', { name: 'Добавить устройство' })
    await opener.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.modal')).toHaveCount(1)

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(0)
    await expect(opener).toBeFocused()
  })

  test('вложенное окно забирает фокус и лежит выше; после его закрытия фокус на кнопке «+», нижнее окно остаётся открытым', async ({ page }) => {
    await OPEN_FORM(page)
    const quickAddButton = page.locator('.modal .quick-add-btn').first()
    await quickAddButton.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.modal')).toHaveCount(2)

    const quickAdd = page.getByRole('dialog', { name: /^Добавить: / })
    await expect(quickAdd).toBeFocused()
    // Слой берётся из стека окон, а не из порядка в DOM: в точке над серединой вложенного окна — оно само, а не форма под ним.
    const onTop = await quickAdd.evaluate((el) => {
      const box = el.getBoundingClientRect()
      return el.contains(document.elementFromPoint(box.x + box.width / 2, box.y + 30))
    })
    expect(onTop).toBe(true)

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(1)
    await expect(quickAddButton).toBeFocused()
  })

  test('пока окно открыто, прокрутка страницы заблокирована, а само окно листается колесом; после закрытия блокировка снята', async ({ page }) => {
    await OPEN_FORM(page)
    await expect(page.locator('body')).toHaveCSS('overflow', 'hidden')

    const overlay = page.locator('.modal-overlay')
    await page.mouse.move(720, 300)
    await page.mouse.wheel(0, 400)
    await expect.poll(() => overlay.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)

    await page.keyboard.press('Escape')
    await expect(page.locator('.modal')).toHaveCount(0)
    await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden')
  })
})
