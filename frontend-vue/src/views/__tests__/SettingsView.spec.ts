import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsView from '../SettingsView.vue'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../../stores/organization'
import { useFormPreferencesStore } from '../../stores/formPreferences'
import { useAuthStore } from '../../stores/auth'
import { usePreferencesStore } from '../../stores/preferences'
import { stubPreferencesApi } from '../../stores/__tests__/preferencesApi'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  // SettingsView теперь рендерит AuthSettingsPanel, который на mount дергает
  // GET /auth/users (аутентификация выключена по умолчанию — см. auth.ts:canManage) —
  // без стаба это настоящий fetch() с относительным URL, падающий в jsdom.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify([]))),
  )
})

describe('SettingsView.vue', () => {
  it('поле по умолчанию предзаполнено текущим наименованием организации', () => {
    const wrapper = mount(SettingsView)
    expect((wrapper.find('.org-name-row input').element as HTMLInputElement).value).toBe(DEFAULT_ORGANIZATION_NAME)
  })

  it('сохраняет новое наименование в стор по клику на "Сохранить"', async () => {
    const wrapper = mount(SettingsView)
    const organization = useOrganizationStore()

    await wrapper.find('.org-name-row input').setValue('ООО «Ромашка»')
    await wrapper.find('.org-name-row button.btn-primary').trigger('click')

    expect(organization.name).toBe('ООО «Ромашка»')
    expect(wrapper.find('.current').text()).toContain('Сохранено')
  })

  it('"Сбросить" возвращает значение по умолчанию', async () => {
    const organization = useOrganizationStore()
    organization.setName('ООО «Ромашка»')
    const wrapper = mount(SettingsView)

    await wrapper.find('.org-name-row button.btn-secondary').trigger('click')

    expect(organization.name).toBe(DEFAULT_ORGANIZATION_NAME)
    expect((wrapper.find('.org-name-row input').element as HTMLInputElement).value).toBe(DEFAULT_ORGANIZATION_NAME)
  })
  describe('общий порог сворачивания списков', () => {
    const input = (wrapper: ReturnType<typeof mount>) => wrapper.find('#collapse-rows')

    it('поле предзаполнено текущим порогом (по умолчанию 10)', () => {
      const wrapper = mount(SettingsView)
      expect((input(wrapper).element as HTMLInputElement).value).toBe('10')
    })

    it('сохраняет введённый порог в стор по клику на «Сохранить»', async () => {
      const wrapper = mount(SettingsView)
      await input(wrapper).setValue('25')
      await wrapper.find('[data-testid="collapse-limit-save"]').trigger('click')

      expect(useFormPreferencesStore().collapseRows).toBe(25)
      expect(wrapper.find('[data-testid="collapse-limit-saved"]').exists()).toBe(true)
    })

    it('недопустимое значение показывает ошибку и не меняет стор', async () => {
      const wrapper = mount(SettingsView)
      const store = useFormPreferencesStore()
      for (const bad of ['0', '', '1001', '2.5']) {
        await input(wrapper).setValue(bad)
        await wrapper.find('[data-testid="collapse-limit-save"]').trigger('click')
        expect(wrapper.find('[data-testid="collapse-limit-error"]').text()).toContain('от 1 до 1000')
        expect(store.collapseRows).toBe(10)
      }
    })

    it('«Сбросить» возвращает 10 и в поле, и в сторе', async () => {
      const store = useFormPreferencesStore()
      store.setCollapseRows(40)
      const wrapper = mount(SettingsView)
      expect((input(wrapper).element as HTMLInputElement).value).toBe('40')

      await wrapper.find('[data-testid="collapse-limit-reset"]').trigger('click')

      expect(store.collapseRows).toBe(10)
      expect((input(wrapper).element as HTMLInputElement).value).toBe('10')
    })
  })
})

describe('SettingsView.vue — настройки хранятся на сервере', () => {
  const orgControls = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.org-name-row input, .org-name-row button')
  const asUser = (role: 'admin' | 'viewer') => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.initialized = true
    auth.user = { id: 'u1', username: 'user', role, is_active: true } as never
  }

  it('при выключенной аутентификации название организации можно менять (реестр открыт целиком)', () => {
    const wrapper = mount(SettingsView)
    expect(orgControls(wrapper).every((el) => el.attributes('disabled') === undefined)).toBe(true)
    expect(wrapper.find('[data-testid="org-readonly-hint"]').exists()).toBe(false)
  })

  it('администратор может менять общее название организации', () => {
    asUser('admin')
    const wrapper = mount(SettingsView)
    expect(orgControls(wrapper).every((el) => el.attributes('disabled') === undefined)).toBe(true)
  })

  it('наблюдатель (viewer) видит название, но поле и кнопки недоступны, с пояснением почему', () => {
    asUser('viewer')
    const wrapper = mount(SettingsView)
    expect(orgControls(wrapper)).toHaveLength(3)
    expect(orgControls(wrapper).every((el) => el.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('[data-testid="org-readonly-hint"]').text()).toContain('только администратор')
  })

  it('наблюдатель может менять личные настройки: порог сворачивания уходит на сервер', async () => {
    asUser('viewer')
    const api = stubPreferencesApi()
    const wrapper = mount(SettingsView)

    await wrapper.find('#collapse-rows').setValue('30')
    await wrapper.find('[data-testid="collapse-limit-save"]').trigger('click')
    await flushPromises()

    expect(api.userPuts).toEqual([{ device_vlan_collapse_rows: 30 }])
    expect(useFormPreferencesStore().collapseRows).toBe(30)
  })

  it('сохранение названия организации уходит на сервер как общая настройка', async () => {
    const api = stubPreferencesApi()
    const wrapper = mount(SettingsView)

    await wrapper.find('.org-name-row input').setValue('ООО «Ромашка»')
    await wrapper.find('.org-name-row button.btn-primary').trigger('click')
    await flushPromises()

    expect(api.globalPuts).toEqual([{ organization_name: 'ООО «Ромашка»' }])
    expect(api.userPuts).toEqual([])
  })
})

describe('SettingsView.vue — подпись, где хранятся личные настройки', () => {
  it('с учётной записью: на сервере, одинаково на всех компьютерах', () => {
    usePreferencesStore().userStorage = 'server'
    const wrapper = mount(SettingsView)
    expect(wrapper.find('[data-testid="personal-storage-note"]').text()).toContain('хранится на сервере')
  })

  it('без аутентификации: в этом браузере', () => {
    usePreferencesStore().userStorage = 'local'
    const wrapper = mount(SettingsView)
    expect(wrapper.find('[data-testid="personal-storage-note"]').text()).toContain('хранится в этом браузере')
    expect(wrapper.text()).toContain('аутентификация выключена')
  })

  it('название организации остаётся общим серверным и в режиме без аутентификации', () => {
    usePreferencesStore().userStorage = 'local'
    const wrapper = mount(SettingsView)
    expect(wrapper.text()).toContain('Общее для всех пользователей и хранится на сервере')
  })

  it('подпись про название по умолчанию не заключает «ООО «Организация»» в ещё одни кавычки (UI-17)', () => {
    const wrapper = mount(SettingsView)

    const hint = wrapper.find('.settings-section .hint').text()
    expect(hint).toContain(`По умолчанию — ${DEFAULT_ORGANIZATION_NAME}.`)
    expect(hint).not.toContain('«ООО «')
    expect(hint).not.toContain('»»')
  })
})
