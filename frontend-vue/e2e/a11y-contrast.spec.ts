import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { openApp } from './fixtures.ts'

// UI-07 (ревью merge/review-2158-executors, §5 «Общий тест»): контраст текста проверяется в настоящем браузере движком axe-core
// для всех трёх акцентных схем. Юнит-тест styles/__tests__/theme.spec.ts считает пары токенов, а axe — реальные пары «цвет текста /
// фактический фон элемента», поэтому ловит случаи, когда токен подставили не на ту подложку.
// Ключ схемы — LOCAL_COLOR_SCHEME_KEY в src/utils/localSettings.ts.
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
