import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { openApp } from './fixtures.ts'
import { cleanupSeeded, seedVirtualMachine } from './seed.ts'

// Оптимистичная блокировка: две вкладки открыли одну запись, одна успела сохранить правку. Вторая раньше молча затирала чужое
// изменение («выигрывает последняя запись»); теперь сервер отвечает 409 STALE_RECORD, а форма спрашивает, что делать. Проверяется
// на настоящем backend и на форме виртуальной машины — токен версии (updated_at) идёт по всей цепочке: список → форма → PUT → ответ.

const CONFLICT_TITLE = 'Запись изменили, пока вы её редактировали'
const EDIT_TITLE = 'Редактировать виртуальную машину'
const MINE = 'правка из вкладки A'
const THEIRS = 'правка из вкладки B'
const ORIGINAL = 'исходное назначение'

let vm: { id: string; name: string }

test.beforeEach(async ({ request }) => {
  vm = await seedVirtualMachine(request, { purpose: ORIGINAL })
})
test.afterEach(async ({ request }) => {
  await cleanupSeeded(request)
})

/** Вкладка со списком ВМ, на котором найдена нужная машина, и открытой формой её редактирования. */
async function openEditForm(context: BrowserContext): Promise<Page> {
  const page = await context.newPage()
  await openApp(page, '/vms')
  await page.getByPlaceholder('Поиск по названию, назначению…').fill(vm.name)
  await page.locator('tr', { hasText: vm.name }).getByRole('button', { name: 'Редактировать' }).click()
  await expect(page.getByRole('dialog', { name: EDIT_TITLE })).toBeVisible()
  // Поля формы заполняются после загрузки вложенных списков; пока они грузятся, «Сохранить» недоступна.
  await expect(page.getByRole('dialog', { name: EDIT_TITLE }).getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled()
  return page
}

async function saveWithPurpose(page: Page, purpose: string): Promise<void> {
  const form = page.getByRole('dialog', { name: EDIT_TITLE })
  await form.getByLabel('Целевое назначение').fill(purpose)
  await form.getByRole('button', { name: 'Сохранить', exact: true }).click()
}

/** Две вкладки открыли форму до любых правок; вкладка B сохранила своё значение, форма в A ещё держит прежнюю версию записи. */
async function twoTabsWithOtherTabSaved(context: BrowserContext): Promise<{ tabA: Page; tabB: Page }> {
  const tabA = await openEditForm(context)
  const tabB = await openEditForm(context)
  await saveWithPurpose(tabB, THEIRS)
  await expect(tabB.getByRole('dialog', { name: EDIT_TITLE })).toHaveCount(0)
  return { tabA, tabB }
}

const purposeOnServer = async (request: import('@playwright/test').APIRequestContext) =>
  ((await (await request.get(`/api/v1/resources/vms/${vm.id}`)).json()) as { purpose: string }).purpose

test.describe('оптимистичная блокировка: две вкладки правят одну запись', () => {
  test('без конкурирующей правки сохранение проходит без вопросов, повторная правка тоже', async ({ context, request }) => {
    const tab = await openEditForm(context)
    await saveWithPurpose(tab, MINE)
    await expect(tab.getByRole('dialog', { name: EDIT_TITLE })).toHaveCount(0)
    await expect(tab.getByRole('alertdialog')).toHaveCount(0)
    expect(await purposeOnServer(request)).toBe(MINE)

    await tab.locator('tr', { hasText: vm.name }).getByRole('button', { name: 'Редактировать' }).click()
    await saveWithPurpose(tab, THEIRS)
    await expect(tab.getByRole('dialog', { name: EDIT_TITLE })).toHaveCount(0)
    await expect(tab.getByRole('alertdialog')).toHaveCount(0)
    expect(await purposeOnServer(request)).toBe(THEIRS)
  })

  test('вторая вкладка видит конфликт, а чужая правка на сервере не затёрта, пока пользователь не решил', async ({ context, request }) => {
    const { tabA } = await twoTabsWithOtherTabSaved(context)
    await saveWithPurpose(tabA, MINE)

    const conflict = tabA.getByRole('alertdialog', { name: CONFLICT_TITLE })
    await expect(conflict).toBeVisible()
    await expect(conflict.getByTestId('stale-record-message')).not.toBeEmpty()
    await expect(tabA.getByRole('dialog', { name: EDIT_TITLE })).toBeVisible() // форма осталась под вопросом
    expect(await purposeOnServer(request)).toBe(THEIRS)
  })

  test('«Сохранить мои изменения»: запись заменяется значениями второй вкладки', async ({ context, request }) => {
    const { tabA } = await twoTabsWithOtherTabSaved(context)
    await saveWithPurpose(tabA, MINE)
    await tabA.getByTestId('stale-record-overwrite').click()

    await expect(tabA.getByRole('alertdialog')).toHaveCount(0)
    await expect(tabA.getByRole('dialog', { name: EDIT_TITLE })).toHaveCount(0)
    expect(await purposeOnServer(request)).toBe(MINE)
  })

  test('«Загрузить свежие данные»: форма закрывается без сохранения, список показывает чужую правку', async ({ context, request }) => {
    const { tabA } = await twoTabsWithOtherTabSaved(context)
    await saveWithPurpose(tabA, MINE)
    await tabA.getByTestId('stale-record-reload').click()

    await expect(tabA.getByRole('alertdialog')).toHaveCount(0)
    await expect(tabA.getByRole('dialog', { name: EDIT_TITLE })).toHaveCount(0)
    await expect(tabA.locator('tr', { hasText: vm.name })).toContainText(THEIRS)
    expect(await purposeOnServer(request)).toBe(THEIRS)
  })

  test('«Остаться в форме»: ничего не сохраняется, значения в форме на месте, повторное сохранение снова спрашивает', async ({ context, request }) => {
    const { tabA } = await twoTabsWithOtherTabSaved(context)
    await saveWithPurpose(tabA, MINE)
    await tabA.getByTestId('stale-record-stay').click()

    await expect(tabA.getByRole('alertdialog')).toHaveCount(0)
    const form = tabA.getByRole('dialog', { name: EDIT_TITLE })
    await expect(form.getByLabel('Целевое назначение')).toHaveValue(MINE)
    expect(await purposeOnServer(request)).toBe(THEIRS)

    await form.getByRole('button', { name: 'Сохранить', exact: true }).click()
    await expect(tabA.getByRole('alertdialog', { name: CONFLICT_TITLE })).toBeVisible()
  })

  test('Esc в окне конфликта — «остаться в форме»: окно закрыто, форма открыта, запись не изменена', async ({ context, request }) => {
    const { tabA } = await twoTabsWithOtherTabSaved(context)
    await saveWithPurpose(tabA, MINE)
    await expect(tabA.getByRole('alertdialog', { name: CONFLICT_TITLE })).toBeVisible()

    await tabA.keyboard.press('Escape')

    await expect(tabA.getByRole('alertdialog')).toHaveCount(0)
    await expect(tabA.getByRole('dialog', { name: EDIT_TITLE })).toBeVisible()
    expect(await purposeOnServer(request)).toBe(THEIRS)
  })
})
