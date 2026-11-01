import { expect, test } from '@playwright/test'
import { findEmptyIcons, observePage, openApp, signInAsAdmin } from './fixtures.ts'

// Каркас приложения: сайдбар, топбар, иконки, шрифты, глобальные стили. Каждая проверка названа номером находки из отчёта
// «Ревью ветки merge/review-2158-executors — веб-интерфейс» (поток A) и падает, если дефект вернётся.

const MENU_ITEMS = '.sidebar .nav a, .sidebar .nav-button'

test.describe('телефон 390×667, вход выполнен', () => {
  test.use({ viewport: { width: 390, height: 667 } })
  test.beforeEach(async ({ page }) => {
    await signInAsAdmin(page)
    await openApp(page, '/dashboard')
  })

  test('UI-1: меню длиннее окна, но каждый пункт, включая «Настройки» и «Выйти», достижим прокруткой', async ({ page }) => {
    await page.locator('.hamburger').click()
    const sidebar = page.locator('.sidebar')
    await expect(sidebar).toHaveClass(/open/)

    // Без этого условия тест ничего бы не доказывал: меню обязано быть выше окна.
    const { scrollHeight, clientHeight } = await sidebar.evaluate((el) => ({ scrollHeight: el.scrollHeight, clientHeight: el.clientHeight }))
    expect(scrollHeight).toBeGreaterThan(clientHeight)
    await expect(sidebar).toHaveCSS('overflow-y', 'auto')

    const items = page.locator(MENU_ITEMS)
    const count = await items.count()
    expect(count).toBeGreaterThanOrEqual(16)
    for (let index = 0; index < count; index++) {
      const item = items.nth(index)
      await item.scrollIntoViewIfNeeded()
      await expect(item, `пункт «${(await item.innerText()).trim()}» не виден целиком`).toBeInViewport({ ratio: 1 })
    }
    await expect(sidebar.getByText('Выйти')).toBeVisible()
  })

  test('UI-10: закрытое меню вне порядка фокуса, открытое закрывается по Esc', async ({ page }) => {
    const sidebar = page.locator('.sidebar')
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('.sidebar')))).toBe(false)
    await expect(sidebar).toHaveCSS('visibility', 'hidden')

    await page.locator('.hamburger').click()
    await expect(sidebar).toHaveCSS('visibility', 'visible')
    await page.keyboard.press('Escape')
    await expect(sidebar).not.toHaveClass(/open/)
    // visibility гаснет с задержкой на время анимации закрытия — проверка сама дожидается.
    await expect(sidebar).toHaveCSS('visibility', 'hidden')
  })

  test('UI-5: топбар остаётся вверху окна при прокрутке длинной страницы', async ({ page }) => {
    await page.evaluate(() => {
      ;(document.querySelector('.content') as HTMLElement).style.minHeight = '3500px'
      window.scrollTo(0, 2200)
    })
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(1000)
    const top = await page.locator('.topbar').evaluate((el) => el.getBoundingClientRect().top)
    expect(top).toBe(0)
    await expect(page.locator('.hamburger')).toBeInViewport({ ratio: 1 })
  })

  test('UI-7 и UI-10: меню пользователя — hover заметен, Esc закрывает и возвращает фокус на чип', async ({ page }) => {
    await page.locator('.user-chip-trigger').click()
    const menu = page.locator('.user-menu')
    await expect(menu).toBeVisible()

    await page.locator('.user-menu-item').first().hover()
    const menuBackground = await menu.evaluate((el) => getComputedStyle(el).backgroundColor)
    // transition фона длится доли секунды — ждём, пока hover-цвет установится и отличится от фона самого меню.
    await expect(page.locator('.user-menu-item').first()).not.toHaveCSS('background-color', menuBackground)

    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)
    await expect(page.locator('.user-chip-trigger')).toBeFocused()

    await page.locator('.user-chip-trigger').hover()
    const topbarBackground = await page.locator('.topbar').evaluate((el) => getComputedStyle(el).backgroundColor)
    await expect(page.locator('.user-chip-trigger')).not.toHaveCSS('background-color', topbarBackground)
  })
})

test.describe('десктоп 1440×900, вход выполнен', () => {
  test.use({ viewport: { width: 1440, height: 900 } })
  test.beforeEach(async ({ page }) => {
    await signInAsAdmin(page)
  })

  test('UI-5: сайдбар и топбар остаются на месте при прокрутке, «Настройки» и «Выйти» всегда в окне', async ({ page }) => {
    await openApp(page, '/dashboard')
    await page.evaluate(() => {
      ;(document.querySelector('.content') as HTMLElement).style.minHeight = '3500px'
      window.scrollTo(0, 2200)
    })
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(1000)

    const sidebar = page.locator('.sidebar')
    expect(await sidebar.evaluate((el) => el.getBoundingClientRect().top)).toBe(0)
    expect(await page.locator('.topbar').evaluate((el) => el.getBoundingClientRect().top)).toBe(0)
    await expect(sidebar.getByText('Настройки')).toBeInViewport({ ratio: 1 })
    await expect(sidebar.getByText('Выйти')).toBeInViewport({ ratio: 1 })
  })

  test('UI-2 и UI-11: иконки пунктов меню все нарисованы и не повторяются, у «Сформировать и скачать» есть значок', async ({ page }) => {
    await openApp(page, '/dashboard')
    const hrefs = await page.locator('.sidebar use').evaluateAll((uses) => uses.map((use) => use.getAttribute('href') ?? ''))
    expect(hrefs.length).toBeGreaterThanOrEqual(17)
    expect(hrefs.filter((href, index) => hrefs.indexOf(href) !== index)).toEqual([])
    expect(await findEmptyIcons(page)).toEqual([])

    // На «Отчёты» — переходом по меню: так проверяется иконка на экране, открытом из каркаса (прямой заход на экран при включённой
    // аутентификации проверяет тест про обновление страницы ниже).
    await page.locator('.sidebar').getByRole('link', { name: 'Отчёты', exact: true }).click()
    await expect(page).toHaveURL(/\/reports$/)
    await page.waitForLoadState('networkidle')
    const downloadIcons = page.locator('svg use[href$="#i-download"]')
    expect(await downloadIcons.count()).toBeGreaterThanOrEqual(1)
    expect(await findEmptyIcons(page)).toEqual([])
  })

  test('UI-8: тёмная цветовая схема объявлена на всём документе', async ({ page }) => {
    await openApp(page, '/dashboard')
    await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark')
  })

  test('UI-6: точка статуса — 6 px с полупрозрачным ореолом, а не сплошной круг 12 px', async ({ page }) => {
    await openApp(page, '/dashboard')
    // Данных в чистой базе нет, поэтому точка создаётся с теми же классами, что в таблицах (стили глобальные, base.css).
    await page.evaluate(() => {
      const probe = document.createElement('div')
      probe.id = 'status-probe'
      probe.innerHTML = '<span class="status on"><span class="status-dot"></span>Да</span>'
      document.body.appendChild(probe)
    })
    const dot = page.locator('#status-probe .status-dot')
    await expect(dot).toHaveCSS('width', '6px')
    await expect(dot).toHaveCSS('height', '6px')
    await expect(dot).toHaveCSS('opacity', '1')
    const { boxShadow, color } = await dot.evaluate((el) => ({ boxShadow: getComputedStyle(el).boxShadow, color: getComputedStyle(el).color }))
    // Ореол есть (spread 3px), но это не сам цвет точки: у него прозрачность.
    expect(boxShadow).toContain('3px')
    expect(boxShadow).not.toContain(color)
    expect(boxShadow).toMatch(/\/\s*0?\.25\)|,\s*0?\.25\)/)
  })

  test('UI-9: шрифты приходят с того же origin, внешних запросов нет, Inter и Golos Text загружены', async ({ page, baseURL }) => {
    const observation = observePage(page, baseURL ?? '')
    const fontResponses: { url: string; status: number; contentType: string }[] = []
    page.on('response', (response) => {
      if (/\.woff2(\?|$)/.test(response.url())) {
        fontResponses.push({ url: response.url(), status: response.status(), contentType: response.headers()['content-type'] ?? '' })
      }
    })
    await openApp(page, '/dashboard')

    expect(observation.foreignRequests).toEqual([])
    // Серверный CSP (font-src 'self') не режет локальные шрифты: ни одной ошибки в консоли.
    expect(observation.consoleErrors).toEqual([])
    expect(fontResponses.length).toBeGreaterThanOrEqual(2)
    for (const response of fontResponses) {
      expect(response.status, response.url).toBe(200)
      expect(response.contentType, response.url).toMatch(/font|woff/)
    }
    const loaded = await page.evaluate(() =>
      Array.from(document.fonts)
        .filter((face) => face.status === 'loaded')
        .map((face) => face.family.replaceAll('"', '')),
    )
    expect(loaded).toEqual(expect.arrayContaining(['Inter Variable', 'Golos Text Variable']))
    await expect(page.locator('.page-title')).toHaveCSS('font-family', /Golos Text Variable/)
  })
})

test.describe('глубокие ссылки при включённой аутентификации', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  // App.vue: раньше при включённой аутентификации init() выставлял enabled = true раньше, чем приходил /auth/me, и watch(needsLogin)
  // на мгновение видел «нужен вход» — уводил на /login с redirect = '/' (в этот момент route ещё стартовый), а после ответа
  // /auth/me экран входа отправлял на /dashboard. Итог: F5 или закладка на любой экран, кроме дашборда, вели на дашборд.
  // Теперь watch молчит, пока auth.init() не закончился, и решение о входе принимает роутер-гард с настоящим адресом.
  test('обновление страницы при включённой аутентификации не теряет текущий экран', async ({ page }) => {
    await signInAsAdmin(page)
    await openApp(page, '/devices')
    await expect(page).toHaveURL(/\/devices$/)

    await page.reload()
    await page.locator('.topbar').waitFor()
    await expect(page).toHaveURL(/\/devices$/)
  })

  test('закладка на экран с параметрами сохраняет и экран, и параметры', async ({ page }) => {
    await signInAsAdmin(page)
    await openApp(page, '/vlans?search=10')
    await expect(page).toHaveURL(/\/vlans\?search=10$/)
  })
})

test.describe('значок вкладки', () => {
  test('/favicon.ico отдаётся без аутентификации как ICO, а index.html на него ссылается', async ({ page, request, baseURL }) => {
    const observation = observePage(page, baseURL ?? '')
    await openApp(page, '/dashboard')

    const response = await request.get('/favicon.ico')
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toBe('image/x-icon')
    const body = await response.body()
    expect([...body.subarray(0, 4)]).toEqual([0, 0, 1, 0]) // заголовок ICO, а не HTML от SPA-фоллбэка

    await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon.ico')
    expect(observation.consoleErrors).toEqual([])
  })
})
