import { expect, test, type Page } from '@playwright/test'
import { openApp, signInAsAdmin } from './fixtures.ts'

// Экраны на ЗАПОЛНЕННЫХ данных (ревью merge/review-2158-executors, §5 «Общий тест», поток Исполнителя 2): чистая база показывает
// только пустые состояния, поэтому дефекты вида «обрезанный плейсхолдер», «селект на 800px», «серийник посреди строки» на ней
// не воспроизводятся (routes.spec.ts ходит именно по пустым экранам).
//
// Данные подставляются перехватом GET-запросов списков (page.route), а не записью в общую базу: все файлы e2e идут параллельно
// на одном backend, и записанные в базу устройства меняли бы результаты routes.spec.ts. Перехват ничего не пишет и действует
// только в странице своего теста. «Стрессовые» значения — те же, что в seed_review_data.py из ревью (название здания в 120
// символов, помещение с длинным названием, длинные названия ИС, серийные номера разной длины, стек из двух устройств).

const LONG_BUILDING = 'Главный центр обработки данных федерального значения имени академика Сергея Павловича Королёва (корпус №3, строение 7Б)'
const LONG_ROOM = 'Помещение с очень длинным названием для проверки переноса текста в таблице'
const LONG_IS_NAME = 'Государственная информационная система автоматизации межведомственного электронного взаимодействия и документооборота'
const LONG_DESCRIPTION = 'очень длинное описание '.repeat(10).trim()

const VIEWPORTS = [
  { name: 'телефон 390×844', width: 390, height: 844 },
  { name: 'планшет 820×1180', width: 820, height: 1180 },
  { name: 'десктоп 1440×900', width: 1440, height: 900 },
]

type Row = Record<string, unknown>

function device(i: number, overrides: Row = {}): Row {
  return {
    id: `dev-id-${i}`,
    device_type_id: 'dt-sw',
    manufacturer_id: null,
    model_id: null,
    serial_number: `SN-${String(i).padStart(5, '0')}-${'X'.repeat(i % 7)}`,
    system_name: `dev-${i}`,
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: i % 3 !== 0,
    building_id: i % 2 ? 'b-1' : 'b-2',
    room_id: i % 2 ? 'r-1' : 'r-2',
    rack_id: null,
    rack_position: null,
    description: i % 5 === 0 ? `Описание устройства ${i} ${LONG_DESCRIPTION}` : null,
    diagram_icon_id: null,
    oac_certificate_number: null,
    oac_certificate_registry_date: null,
    management_interface: '',
    management_ips: `10.0.${i}.1`,
    interface_count: 0,
    embedded_os_name: '',
    embedded_os_version: '',
    vlan_summary: '',
    stack_id: null,
    stack_name: null,
    stack_position: null,
    ...overrides,
  }
}

/** 13 устройств dev-1…dev-12 + dev-0 в порядке строковой сортировки сервера («dev-1, dev-10, dev-11, dev-12, dev-2, …») и стек из двух. */
function devicesPayload(): Row[] {
  const numbers = Array.from({ length: 13 }, (_, i) => i)
  const byString = [...numbers].sort((a, b) => String(a).localeCompare(String(b)))
  const single = byString.map((i) => device(i))
  const stack = [1, 2].map((p) =>
    device(100 + p, { system_name: `stk-${p}`, serial_number: `STK-0000${p}`, stack_id: 'stack-1', stack_name: 'Стек-1', stack_position: p }),
  )
  return [...single, ...stack]
}

/** «ИС 0»…«ИС 11» и одна с очень длинным названием; сервер отдаёт по строке: «ИС 0, ИС 1, ИС 10, ИС 11, ИС 2, …». */
function systemsPayload(): Row[] {
  const names = Array.from({ length: 12 }, (_, i) => `ИС ${i}`)
  names.sort((a, b) => a.localeCompare(b))
  const rows = names.map((name, i) => ({
    id: `is-${i}`,
    number: `ИС-${String(i).padStart(3, '0')}`,
    name,
    type: 'ГИС',
    description: `Описание ${name} `.repeat(i % 4 === 0 ? 12 : 1).trim(),
    purpose: `Назначение ${i}`,
    localization: null,
    support_organization_id: null,
    support_method_id: null,
    process_description: null,
    siem_enabled: i % 2 === 0,
    crypto_protection_enabled: false,
    crypto_protection_description_id: null,
    ip_addresses: [`192.168.${i}.10`],
  }))
  rows.push({ ...rows[0], id: 'is-long', name: `${LONG_IS_NAME} 99`, purpose: 'Назначение '.repeat(20).trim() })
  return rows
}

function resourcePage(items: Row[]) {
  return { items, total: items.length, offset: 0, limit: 500 }
}

/** Подменяет списки, из которых экраны строят таблицы; остальные запросы идут в настоящий backend (пустая база). */
async function mockFilledData(page: Page) {
  const resource = (name: string, items: Row[]) =>
    page.route(new RegExp(`/api/v1/resources/${name}(\\?|$)`), (route) => route.fulfill({ json: resourcePage(items) }))
  await resource('device-types', [
    { id: 'dt-sw', name: 'Коммутатор' },
    { id: 'dt-srv', name: 'Сервер' },
  ])
  await resource('buildings', [
    { id: 'b-1', name: 'ЦОД-1' },
    { id: 'b-2', name: LONG_BUILDING },
  ])
  await resource('rooms', [
    { id: 'r-1', name: 'Серверная 1', building_id: 'b-1' },
    { id: 'r-2', name: LONG_ROOM, building_id: 'b-2' },
  ])
  const devices = devicesPayload()
  await page.route(/\/api\/v1\/devices(\?|$)/, (route) => route.fulfill({ json: { items: devices, total: devices.length } }))
  await page.route(/\/api\/v1\/information-systems(\?|$)/, (route) => route.fulfill({ json: systemsPayload() }))
}

/** Ширина плейсхолдера против ширины, доступной тексту в поле: обрезанный плейсхолдер даёт textWidth > available. */
async function placeholderFit(page: Page, selector: string): Promise<{ text: string; textWidth: number; available: number }> {
  return page
    .locator(selector)
    .first()
    .evaluate((el) => {
      const input = el as HTMLInputElement
      const style = getComputedStyle(input)
      const context = document.createElement('canvas').getContext('2d')!
      context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      return {
        text: input.placeholder,
        textWidth: context.measureText(input.placeholder).width,
        available: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      }
    })
}

for (const viewport of VIEWPORTS) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    // UI-10: плейсхолдеры поиска помещаются целиком на всех четырёх экранах.
    for (const [route, label] of [
      ['/devices', 'устройства'],
      ['/connections', 'подключения'],
      ['/information-systems', 'информационные системы'],
      ['/vlans', 'VLAN'],
    ] as const) {
      test(`UI-10: ${label} — плейсхолдер поиска не обрезан`, async ({ page }) => {
        await mockFilledData(page)
        await openApp(page, route)

        const { text, textWidth, available } = await placeholderFit(page, '.search-box input')
        expect(textWidth, `«${text}»: нужно ${Math.ceil(textWidth)}px, в поле ${Math.floor(available)}px`).toBeLessThanOrEqual(available)
      })
    }

    // Страница не шире окна и на заполненных данных (на пустых это проверяет routes.spec.ts).
    for (const route of ['/devices', '/connections', '/information-systems', '/vlans']) {
      test(`${route}: на заполненных данных нет горизонтальной прокрутки страницы`, async ({ page }) => {
        await mockFilledData(page)
        await openApp(page, route)

        const { scrollWidth, innerWidth, content } = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          content: (document.querySelector('.content')?.scrollWidth ?? 0) - (document.querySelector('.content')?.clientWidth ?? 0),
        }))
        expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
        expect(content).toBeLessThanOrEqual(0)
      })
    }

    // UI-03: все панели «Настроек» одинаково оформлены, поле пароля вмещает плейсхолдер.
    test('UI-03: заголовки и подписи панелей «Настроек» одинаковы, плейсхолдер пароля не обрезан', async ({ page }) => {
      await signInAsAdmin(page)
      await openApp(page, '/settings')

      const panels = await page.locator('.settings-section').evaluateAll((sections) =>
        sections.map((section) => {
          const h2 = getComputedStyle(section.querySelector('h2')!)
          const hint = section.querySelector('.hint')
          const hintStyle = hint ? getComputedStyle(hint) : null
          return {
            title: section.querySelector('h2')!.textContent,
            h2Size: h2.fontSize,
            h2Family: h2.fontFamily,
            hintSize: hintStyle?.fontSize,
            hintColor: hintStyle?.color,
          }
        }),
      )
      expect(panels.length).toBeGreaterThanOrEqual(5)
      expect(panels.map((p) => p.title)).toEqual(expect.arrayContaining(['Аутентификация', 'Моя учётная запись']))
      expect(new Set(panels.map((p) => p.h2Size)).size, `размеры h2: ${JSON.stringify(panels.map((p) => [p.title, p.h2Size]))}`).toBe(1)
      expect(new Set(panels.map((p) => p.h2Family)).size).toBe(1)
      const hints = panels.filter((p) => p.hintSize !== undefined)
      expect(new Set(hints.map((p) => p.hintSize)).size).toBe(1)
      expect(new Set(hints.map((p) => p.hintColor)).size).toBe(1)

      const { text, textWidth, available } = await placeholderFit(page, '.new-user-row input[type="password"]')
      expect(textWidth, `«${text}»: нужно ${Math.ceil(textWidth)}px, в поле ${Math.floor(available)}px`).toBeLessThanOrEqual(available)
    })
  })
}

test.describe('десктоп 1440×900: заполненные данные', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  // UI-11: селект «Здание» не растягивается по самой длинной опции.
  test('UI-11: селекты фильтров устройств — 200px при названии здания в 120 символов', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    const widths = await page.locator('.filter-fields select.fbtn').evaluateAll((selects) => selects.map((s) => Math.round(s.getBoundingClientRect().width)))
    expect(widths).toHaveLength(2)
    for (const width of widths) expect(width).toBeLessThanOrEqual(210)
    expect(widths[0], 'селекты «Здание» и «Тип устройства» одной ширины').toBe(widths[1])
  })

  // UI-11: кнопки действий — одним блоком в одной строке, «Визуальный режим» не отрывается.
  test('UI-11: «Визуальный режим» на подключениях в одной строке с «Обновить» и «Добавить подключение»', async ({ page }) => {
    await openApp(page, '/connections')

    const buttons = page.locator('.filter-actions .btn')
    await expect(buttons).toHaveCount(3)
    const boxes = await buttons.evaluateAll((els) => els.map((el) => ({ label: el.textContent?.trim(), ...el.getBoundingClientRect().toJSON() })))
    expect(new Set(boxes.map((b) => Math.round(b.top))).size, `кнопки на разных строках: ${JSON.stringify(boxes.map((b) => [b.label, b.top]))}`).toBe(1)
    expect(boxes.map((b) => b.label)).toEqual(['Обновить', 'Визуальный режим', 'Добавить подключение'])

    // группа прижата к правому краю панели
    const { actionsRight, barRight } = await page.evaluate(() => ({
      actionsRight: document.querySelector('.filter-actions')!.getBoundingClientRect().right,
      barRight: document.querySelector('.filter-bar')!.getBoundingClientRect().right,
    }))
    expect(Math.abs(barRight - actionsRight)).toBeLessThanOrEqual(1)
  })

  // UI-12: нулевые карточки не окрашены как предупреждение (на пустой базе «Неактивные» = «Расхождения» = 0).
  test('UI-12: нулевые «Неактивные» и «Расхождения портов» того же цвета, что обычная карточка', async ({ page }) => {
    await openApp(page, '/connections')

    const colorOf = (label: string) =>
      page
        .locator('.stat-card', { hasText: label })
        .locator('.num')
        .evaluate((el) => getComputedStyle(el).color)
    const normal = await colorOf('Всего подключений')
    expect(await colorOf('Неактивные')).toBe(normal)
    expect(await colorOf('Расхождения портов')).toBe(normal)
  })

  test('UI-12: «Нет» в столбцах SIEM и СКЗИ — приглушённый цвет, а не цвет предупреждения', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/information-systems')

    const muted = await page
      .locator('.stat-card .lbl')
      .first()
      .evaluate((el) => getComputedStyle(el).color)
    const no = page.locator('tbody .status.off.neutral').first()
    await expect(no).toHaveText('Нет')
    expect(await no.evaluate((el) => getComputedStyle(el).color)).toBe(muted)
    const yes = page.locator('tbody .status.on').first()
    expect(await yes.evaluate((el) => getComputedStyle(el).color)).not.toBe(muted)
  })

  // UI-13: естественная сортировка, а не строковая.
  test('UI-13: информационные системы идут «ИС 0, ИС 1, ИС 2, …», а не «ИС 0, ИС 1, ИС 10, …»', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/information-systems')

    // Система с очень длинным названием («Государственная …») по алфавиту стоит раньше «ИС …» — в проверке порядка чисел она не нужна.
    const names = (await page.locator('tbody .isname').allTextContents()).filter((name) => /^ИС \d+$/.test(name))
    expect(names.slice(0, 5)).toEqual(['ИС 0', 'ИС 1', 'ИС 2', 'ИС 3', 'ИС 4'])
  })

  test('UI-13: устройства идут «dev-0, dev-1, dev-2, …», а не «dev-0, dev-1, dev-10, …»', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    const names = await page.locator('tbody .devname').allTextContents()
    expect(names.slice(0, 6)).toEqual(['dev-0', 'dev-1', 'dev-2', 'dev-3', 'dev-4', 'dev-5'])
  })

  // UI-14: серийный номер в одну строку.
  test('UI-14: серийные номера не переносятся посреди значения', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    const cells = await page
      .locator('td.serial-cell .clip')
      .evaluateAll((els) =>
        els.map((el) => ({ text: el.textContent, height: el.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(el).lineHeight) || 18 })),
      )
    expect(cells.length).toBeGreaterThan(0)
    for (const cell of cells) expect(cell.height, `«${cell.text}» занял несколько строк`).toBeLessThan(cell.lineHeight * 1.5)
  })

  // UI-09: стек — одна строка; подпись называет обе величины.
  test('UI-09: при стеке подпись счётчика называет строки и устройства', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    // 13 одиночных устройств + стек из двух = 14 строк и 15 устройств
    await expect(page.locator('.table-foot span').first()).toHaveText('Показано 1–6 из 14 строк (устройств: 15)')
  })
})

test.describe('телефон 390×844: таблицы с заполненными данными', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  // UI-06: подсказка прокрутки и ограниченная высота строк.
  test('UI-06: у таблицы устройств затухает правый край, после прокрутки до конца — левый', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    const wrap = page.locator('.table-wrap')
    await expect(wrap).toHaveClass(/shade-right/)
    await expect(wrap).not.toHaveClass(/shade-left/)
    await expect(wrap).toHaveAttribute('tabindex', '0')

    await wrap.evaluate((el) => {
      el.scrollLeft = el.scrollWidth
    })
    await expect(wrap).toHaveClass(/shade-left/)
    await expect(wrap).not.toHaveClass(/shade-right/)
  })

  test('UI-06: строка с длинным зданием, помещением и описанием не выше 110px', async ({ page }) => {
    await mockFilledData(page)
    await openApp(page, '/devices')

    const heights = await page
      .locator('tbody tr:not(.stack-summary-row)')
      .evaluateAll((rows) => rows.map((row) => Math.round(row.getBoundingClientRect().height)))
    expect(heights.length).toBeGreaterThan(0)
    for (const height of heights) expect(height).toBeLessThanOrEqual(110)
  })

  // Подсказка не должна врать при любой ширине: тень и tabindex есть тогда и только тогда, когда таблица действительно шире окна.
  // Ширина «впритык» зависит от версии Chromium и растеризации шрифта (на стрессовых данных у таблицы при 1440 px запас ≈ 10 px:
  // в CI на другой сборке браузера она оказалась на пару пикселей шире окна), поэтому факт переполнения измеряется, а не предполагается.
  test('UI-06: подсказка прокрутки совпадает с фактом — тень и tabindex только если таблица шире окна (1440)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await mockFilledData(page)
    await openApp(page, '/devices')

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

  // Минимальная ширина таблицы ≈ 1160 px, окно 1920 даёт ≈ 1650 px — запас, не зависящий от браузера: подсказки нет.
  test('UI-06: на широком десктопе (1920) подсказка прокрутки не показывается — таблица помещается целиком', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockFilledData(page)
    await openApp(page, '/devices')

    const wrap = page.locator('.table-wrap')
    await expect(wrap).not.toHaveClass(/shade-(left|right)/)
    await expect(wrap).not.toHaveAttribute('tabindex', /.*/)
  })
})

// Проверки находок Исполнителя 1 (UI-01 «диаграмма вписана в холст», UI-04 «Esc закрывает модалку») после слияния потоков живут
// рядом с кодом, который они проверяют: e2e/diagram-filled.spec.ts (данные диаграммы создаются через API самим тестом, а не
// передаются в E2E_DIAGRAM_ID) и e2e/modals.spec.ts.
