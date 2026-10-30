// B-04: формы-модалки в режиме «только просмотр» для роли viewer (composables/useReadOnlyForm.ts).
// Поля отключены одним <fieldset disabled>, кнопки «Сохранить» нет, «Отмена» превращается в «Закрыть»,
// а submit() ничего не отправляет на сервер — даже если форму отправили в обход кнопки (Enter в поле и т.п.).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import DeviceFormModal from '../DeviceFormModal.vue'
import VMFormModal from '../VMFormModal.vue'
import ContainerFormModal from '../ContainerFormModal.vue'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import InformationSystemFormModal from '../InformationSystemFormModal.vue'
import VLANFormModal from '../VLANFormModal.vue'
import DeviceStackFormModal from '../DeviceStackFormModal.vue'
import CatalogRecordFormModal from '../CatalogRecordFormModal.vue'
import StructuralUnitFormModal from '../StructuralUnitFormModal.vue'
import BuildingFormModal from '../BuildingFormModal.vue'
import RoomFormModal from '../RoomFormModal.vue'
import RackFormModal from '../RackFormModal.vue'
import VLANDomainFormModal from '../VLANDomainFormModal.vue'
import PortSyncRuleFormModal from '../PortSyncRuleFormModal.vue'
import ReportTemplateFormModal from '../ReportTemplateFormModal.vue'

import { useAuthStore } from '../../stores/auth'
import { useCatalogsStore } from '../../stores/catalogs'
import type { AuthUser } from '../../api/types'

type Role = 'viewer' | 'admin' | 'auth-off'

function setRole(role: Role) {
  const auth = useAuthStore()
  auth.enabled = role !== 'auth-off'
  auth.user =
    role === 'auth-off'
      ? null
      : ({ id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } as AuthUser)
}

const MODALS: Array<{ name: string; component: object; props: Record<string, unknown> }> = [
  { name: 'DeviceFormModal', component: DeviceFormModal, props: { device: null } },
  { name: 'VMFormModal', component: VMFormModal, props: { vm: null } },
  { name: 'ContainerFormModal', component: ContainerFormModal, props: { container: null } },
  { name: 'ConnectionFormModal', component: ConnectionFormModal, props: { connection: null } },
  { name: 'InformationSystemFormModal', component: InformationSystemFormModal, props: { system: null } },
  { name: 'VLANFormModal', component: VLANFormModal, props: { definition: null } },
  { name: 'DeviceStackFormModal', component: DeviceStackFormModal, props: { stack: null } },
  { name: 'CatalogRecordFormModal', component: CatalogRecordFormModal, props: { resource: 'device-types', item: null } },
  { name: 'StructuralUnitFormModal', component: StructuralUnitFormModal, props: { unit: null, defaultParentId: null } },
  { name: 'BuildingFormModal', component: BuildingFormModal, props: { building: null } },
  { name: 'RoomFormModal', component: RoomFormModal, props: { room: null, buildingId: 'b-1' } },
  { name: 'RackFormModal', component: RackFormModal, props: { rack: null, roomId: 'r-1' } },
  { name: 'VLANDomainFormModal', component: VLANDomainFormModal, props: { domain: null } },
  { name: 'PortSyncRuleFormModal', component: PortSyncRuleFormModal, props: { rule: null } },
  { name: 'ReportTemplateFormModal', component: ReportTemplateFormModal, props: { template: null } },
]

let wrapper: VueWrapper | null = null
let fetchMock: ReturnType<typeof vi.fn>
const writeCalls = () =>
  fetchMock.mock.calls.filter(([, init]) => ['POST', 'PUT', 'DELETE', 'PATCH'].includes((init as RequestInit | undefined)?.method ?? 'GET'))

async function mountModal(m: (typeof MODALS)[number]) {
  // Teleport (CatalogRecordFormModal) выносит разметку в body — поэтому монтируем в документ и ищем по нему.
  wrapper = mount(m.component, { props: m.props, attachTo: document.body })
  await flushPromises()
  return document.body
}

/** Заполняет поля формы правдоподобными значениями, чтобы валидация пропустила отправку, — иначе проверка
 * «ничего не отправлено» проходила бы на пустой форме сама по себе, а не благодаря режиму просмотра. */
function fillForm(root: HTMLElement) {
  const fire = (el: Element, type: string) => el.dispatchEvent(new Event(type, { bubbles: true }))
  root.querySelectorAll('form input, form textarea').forEach((el) => {
    const input = el as HTMLInputElement
    if (input.type === 'checkbox' || input.type === 'radio' || input.type === 'hidden') return
    input.value = input.type === 'number' ? '10' : input.type === 'password' ? 'Passw0rd-12345' : 'Тест'
    fire(input, 'input')
  })
  root.querySelectorAll('form select').forEach((el) => {
    const select = el as HTMLSelectElement
    const option = Array.from(select.options).find((o) => o.value)
    if (option) {
      select.value = option.value
      fire(select, 'change')
    }
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.body.innerHTML = ''
  fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 })))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
  const catalogs = useCatalogsStore()
  catalogs.items['device-types'] = []
  catalogs.loaded = true
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe.each(MODALS)('B-04: $name в режиме просмотра', (m) => {
  it('viewer: поля отключены (fieldset disabled), «Сохранить» нет, вместо «Отмена» — «Закрыть»', async () => {
    setRole('viewer')
    const body = await mountModal(m)

    const fieldset = body.querySelector('fieldset.readonly-fieldset')
    expect(fieldset, 'у формы должен быть fieldset.readonly-fieldset').not.toBeNull()
    expect((fieldset as HTMLFieldSetElement).disabled).toBe(true)

    const foot = body.querySelector('.modal-foot') as HTMLElement
    expect(foot.querySelector('.btn-primary'), 'кнопки «Сохранить»/«Добавить» быть не должно').toBeNull()
    expect(foot.textContent).toContain('Закрыть')
    expect(foot.textContent).not.toContain('Отмена')
  })

  it('viewer: отправка формы в обход кнопки (submit) ничего не отправляет на сервер', async () => {
    setRole('viewer')
    const body = await mountModal(m)
    fillForm(body)
    await flushPromises()
    fetchMock.mockClear()

    const form = body.querySelector('form') as HTMLFormElement
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()

    expect(writeCalls()).toHaveLength(0)
  })

  it.each<Role>(['admin', 'auth-off'])('%s: поля доступны, кнопка сохранения и «Отмена» на месте', async (role) => {
    setRole(role)
    const body = await mountModal(m)

    const fieldset = body.querySelector('fieldset.readonly-fieldset') as HTMLFieldSetElement
    expect(fieldset.disabled).toBe(false)

    const foot = body.querySelector('.modal-foot') as HTMLElement
    expect(foot.querySelector('.btn-primary')).not.toBeNull()
    expect(foot.textContent).toContain('Отмена')
  })
})
