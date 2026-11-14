import { test } from '@playwright/test'
import { openApp, signInAsAdmin } from './fixtures.ts'

// ВРЕМЕННО (отладка Playwright 1.65): замер подсказки поля пароля и платформенного шрифта. Не попадает в main.
test.use({ viewport: { width: 390, height: 844 } })

test('замер плейсхолдера пароля', async ({ page }) => {
  await signInAsAdmin(page)
  await openApp(page, '/settings')
  const selector = '.new-user-row input[type="password"]'
  const measured = await page.locator(selector).first().evaluate((el) => {
    const input = el as HTMLInputElement
    const style = getComputedStyle(input)
    const context = document.createElement('canvas').getContext('2d')!
    context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
    const texts = ['Пароль (мин. 8 символов, буквы и цифры)', 'Пароль (мин. 8, буквы и цифры)', 'Пароль: от 8 символов, буквы и цифры', 'Имя пользователя']
    return {
      userAgent: navigator.userAgent,
      fontFamily: style.fontFamily,
      fontSize: style.fontSize,
      clientWidth: input.clientWidth,
      available: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      widths: Object.fromEntries(texts.map((text) => [text, Math.round(context.measureText(text).width * 10) / 10])),
    }
  })
  const client = await page.context().newCDPSession(page)
  await client.send('DOM.enable')
  await client.send('CSS.enable')
  const { root } = await client.send('DOM.getDocument')
  const { nodeId } = await client.send('DOM.querySelector', { nodeId: root.nodeId, selector })
  const platform = await client.send('CSS.getPlatformFontsForNode', { nodeId })
  console.log('MEASURE ' + JSON.stringify({ ...measured, platformFonts: platform.fonts }))
})
