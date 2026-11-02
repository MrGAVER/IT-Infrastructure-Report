import type { Page } from '@playwright/test'

// Ключ токена сессии в localStorage — TOKEN_STORAGE_KEY в src/api/client.ts. Без токена стор auth не спрашивает /auth/me.
const TOKEN_STORAGE_KEY = 'itr:auth-token'

const ADMIN = {
  id: 'e2e-admin',
  username: 'admin',
  role: 'admin',
  is_active: true,
  last_login_at: null,
  locked: false,
  created_at: '2026-01-01T00:00:00',
}

/**
 * Включает в интерфейсе аутентификацию и входит администратором, не трогая реальный backend (на нём она выключена):
 * с учётной записью в сайдбаре появляются блок пользователя и «Выйти», а в топбаре — чип с меню — то есть самое длинное меню.
 * Вызывать до page.goto().
 */
export async function signInAsAdmin(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/status', (route) => route.fulfill({ json: { enabled: true } }))
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: { enabled: true, user: ADMIN } }))
  await page.addInitScript((key) => localStorage.setItem(key, 'e2e-token'), TOKEN_STORAGE_KEY)
}

/** Открывает маршрут и ждёт, пока отрисуется каркас и догрузятся шрифты и данные экрана. */
export async function openApp(page: Page, route: string): Promise<void> {
  await page.goto(route)
  await page.locator('.topbar').waitFor()
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
}

export interface PageObservation {
  /** Сообщения console.error (в том числе нарушения CSP и «Failed to load resource»). */
  consoleErrors: string[]
  /** Необработанные исключения в странице. */
  pageErrors: string[]
  /** Запросы, завершившиеся сетевой ошибкой. */
  failedRequests: string[]
  /** Запросы не к origin приложения (data:/blob: не в счёт) — внешний CDN, шрифты, аналитика. */
  foreignRequests: string[]
}

/** Подписывается на события страницы; вызывать до page.goto(). Результат наполняется по ходу работы. */
export function observePage(page: Page, origin: string): PageObservation {
  const observation: PageObservation = { consoleErrors: [], pageErrors: [], failedRequests: [], foreignRequests: [] }
  page.on('console', (message) => {
    if (message.type() === 'error') observation.consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => observation.pageErrors.push(error.message))
  page.on('requestfailed', (request) => observation.failedRequests.push(`${request.url()} — ${request.failure()?.errorText ?? 'неизвестная ошибка'}`))
  page.on('request', (request) => {
    const url = request.url()
    if (!url.startsWith(origin) && !url.startsWith('data:') && !url.startsWith('blob:')) observation.foreignRequests.push(url)
  })
  return observation
}

/**
 * Иконки спрайта, которые на странице видны, но не нарисовались: <use> на отсутствующий символ даёт пустой bbox
 * (так выглядели кнопки «Сформировать и скачать» без i-download). Возвращает href таких <use>.
 */
export async function findEmptyIcons(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('svg use'))
      .filter((use) => {
        const svg = (use as SVGUseElement).ownerSVGElement
        return svg !== null && svg.getBoundingClientRect().width > 0
      })
      .filter((use) => (use as SVGUseElement).getBBox().width === 0)
      .map((use) => use.getAttribute('href') ?? ''),
  )
}
