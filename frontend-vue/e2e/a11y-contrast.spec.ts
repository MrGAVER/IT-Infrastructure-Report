import AxeBuilder from '@axe-core/playwright'
import axe from 'axe-core'
import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'

// UI-07 (ревью merge/review-2158-executors, §5 «Общий тест»): контраст текста проверяется в настоящем браузере движком axe-core
// для всех трёх акцентных схем. Юнит-тест styles/__tests__/theme.spec.ts считает пары токенов, а axe — реальные пары «цвет текста /
// фактический фон элемента», поэтому ловит случаи, когда токен подставили не на ту подложку.
// Ключ схемы — LOCAL_COLOR_SCHEME_KEY в src/utils/localSettings.ts.
//
// Раздел 5 ревью ветки fix/code-review-main-f06-stage2-f05 (frontend п. 3): в тот же a11y-набор добавлена проверка живых областей —
// того, чего не видит ни один юнит-тест: что уведомление лежит в живой области в настоящем дереве доступности браузера (дефект FE-02:
// у ToastHost не было ни aria-live, ни ролей, и скринридер молчал о результате действия). См. блок «живые области» ниже.
const SCHEMES = ['teal', 'indigo', 'copper'] as const
const ROUTES = ['/dashboard', '/devices', '/connections', '/vlans', '/settings', '/audit-log'] as const

test.use({ viewport: { width: 1440, height: 900 } })

for (const scheme of SCHEMES) {
  test.describe(`схема «${scheme}»`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(([key, value]) => localStorage.setItem(key, value), ['itr.colorScheme', scheme] as const)
    })

    for (const route of ROUTES) {
      test(`${route}: контраст текста не ниже WCAG AA`, async ({ page }) => {
        await openApp(page, route)
        await expect(page.locator('html')).toHaveAttribute('data-scheme', scheme)
        const result = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze()
        const report = result.violations.flatMap((violation) =>
          violation.nodes.map((node) => `${node.target.join(' ')} — ${node.any[0]?.message ?? violation.help}`),
        )
        expect(report, 'нарушения контраста').toEqual([])
      })
    }
  })
}

// --- Живые области (WCAG 2.2, 4.1.3 «Status Messages») -----------------------------------------------------------------------
//
// В axe нет правила «этому элементу место в живой области» — он видит только неверное использование ARIA. Поэтому добавлено своё
// правило: каждый `.toast` обязан лежать внутри живой области. Оно срабатывает на любом уведомлении, которое появится на странице,
// и потому ловит дефект класса FE-02 независимо от того, кто и как его вызвал. Проверка «до первого уведомления» (область уже в DOM
// и пуста) — отдельным тестом: часть скринридеров не объявляет содержимое области, созданной вместе с ним.
const LIVE_REGION_SELECTOR = '[role="status"], [role="alert"], [role="log"], [aria-live="polite"], [aria-live="assertive"]'

const TOAST_IN_LIVE_REGION = {
  checks: [
    {
      id: 'inside-live-region',
      // Строка, а не функция: конфигурация уходит в страницу сериализованной.
      evaluate: `function (node) { return node.closest(${JSON.stringify(LIVE_REGION_SELECTOR)}) !== null }`,
      metadata: {
        impact: 'serious',
        messages: { pass: 'Уведомление лежит в живой области', fail: 'Уведомление вне живой области: скринридер его не озвучит' },
      },
    },
  ],
  rules: [
    {
      id: 'toast-in-live-region',
      selector: '.toast',
      any: ['inside-live-region'],
      tags: ['custom', 'wcag2a', 'wcag413'],
      metadata: {
        description: 'Уведомление должно лежать в живой области',
        help: 'Уведомление (.toast) должно быть внутри role="status" / role="alert" / aria-live',
      },
    },
  ],
}

// Правила axe про корректность ARIA: живая область с неверной ролью или значением атрибута молчит так же, как отсутствующая.
const ARIA_RULES = ['aria-allowed-attr', 'aria-allowed-role', 'aria-roles', 'aria-valid-attr', 'aria-valid-attr-value', 'aria-required-attr']

// AxeBuilder (4.x) не принимает свои правила, поэтому конфигурация дописывается к исходнику axe-core, который он вставляет в страницу.
const AXE_WITH_LIVE_REGION_RULE = `${axe.source};axe.configure(${JSON.stringify(TOAST_IN_LIVE_REGION)})`

async function analyzeLiveRegions(page: import('@playwright/test').Page) {
  const result = await new AxeBuilder({ page, axeSource: AXE_WITH_LIVE_REGION_RULE }).withRules([...ARIA_RULES, 'toast-in-live-region']).analyze()
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.target.join(' ')} — ${node.any[0]?.message ?? violation.help}`),
  )
}

/** Вызывает уведомление об ошибке настоящим действием пользователя: сохранение названия организации, на которое сервер отвечает 500. */
async function triggerErrorToast(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/preferences/global', (route) => route.fulfill({ status: 500, json: { detail: 'Сбой сохранения (проверка e2e)' } }))
  await openApp(page, '/settings')
  await page.getByPlaceholder('Наименование организации').fill('Проверка живой области')
  await page.getByRole('button', { name: 'Сохранить' }).first().click()
}

test.describe('живые области: уведомления', () => {
  test('обе области есть в DOM до первого уведомления и пусты: роль и aria-live у каждой заданы', async ({ page }) => {
    await openApp(page, '/dashboard')
    const status = page.locator('.toast-host [role="status"]')
    const alert = page.locator('.toast-host [role="alert"]')
    await expect(status).toHaveCount(1)
    await expect(alert).toHaveCount(1)
    await expect(status).toHaveAttribute('aria-live', 'polite')
    await expect(alert).toHaveAttribute('aria-live', 'assertive')
    await expect(page.locator('.toast-host .toast')).toHaveCount(0)
    // Те же области в дереве доступности браузера, а не только в разметке.
    await expect(page.getByRole('status').filter({ has: page.locator('.toast') })).toHaveCount(0)
  })

  test('ошибка действия появляется внутри области с role="alert"; правило «уведомление в живой области» и ARIA-правила чисты', async ({ page }) => {
    await triggerErrorToast(page)
    const toast = page.locator('.toast.error')
    await expect(toast).toHaveCount(1)
    await expect(page.locator('.toast-host [role="alert"] .toast.error')).toHaveCount(1)
    await expect(page.getByRole('alert').filter({ hasText: 'Сбой сохранения' })).toBeVisible()
    expect(await analyzeLiveRegions(page), 'нарушения живых областей').toEqual([])
  })

  test('контроль самого правила: уведомление вне живой области даёт нарушение (так выглядел дефект FE-02)', async ({ page }) => {
    await openApp(page, '/dashboard')
    await page.evaluate(() => {
      const stray = document.createElement('div')
      stray.className = 'toast'
      stray.textContent = 'Уведомление без живой области'
      document.body.append(stray)
    })
    const violations = await analyzeLiveRegions(page)
    expect(violations.filter((line) => line.startsWith('toast-in-live-region'))).toHaveLength(1)
  })
})
