// Разграничение прав на настройки аудита во фронтенде: кнопку видит только тот, кому доступен сам журнал. Сервер проверяет роль независимо
// (backend/tests/test_audit_settings_api.py), здесь — что интерфейс не рисует элементы, которые гарантированно закончатся 403.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditSettingsButton from '../AuditSettingsButton.vue'
import { useAuthStore } from '../../stores/auth'
import { stubAuditSettingsApi } from '../../stores/__tests__/auditSettingsApi'

const button = (w: ReturnType<typeof mount>) => w.find('[data-testid="audit-settings-open"]')
const modal = (w: ReturnType<typeof mount>) => w.find('[data-testid="audit-settings-modal"]')

function asUser(role: 'admin' | 'viewer') {
  const auth = useAuthStore()
  auth.enabled = true
  auth.initialized = true
  auth.user = { id: 'u1', username: role, role, is_active: true } as never
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('AuditSettingsButton.vue — права', () => {
  it('администратор видит кнопку', () => {
    asUser('admin')
    expect(button(mount(AuditSettingsButton)).text()).toBe('Настройки аудита')
  })

  it('при выключенной аутентификации (один пользователь, журнал открыт) кнопка есть', () => {
    expect(button(mount(AuditSettingsButton)).exists()).toBe(true)
  })

  it('наблюдатель (viewer) кнопки не видит и запросов к настройкам не делает', () => {
    asUser('viewer')
    const api = stubAuditSettingsApi()

    const wrapper = mount(AuditSettingsButton)

    expect(button(wrapper).exists()).toBe(false)
    expect(wrapper.html()).not.toContain('Настройки аудита')
    expect(api.requests).toEqual([])
  })

  it('включённая аутентификация без вошедшего пользователя — кнопки нет', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = null
    expect(button(mount(AuditSettingsButton)).exists()).toBe(false)
  })

  it('роль понизили, пока экран был открыт: кнопка исчезает вместе с окном', async () => {
    asUser('admin')
    stubAuditSettingsApi()
    const wrapper = mount(AuditSettingsButton)
    await button(wrapper).trigger('click')
    await flushPromises()
    expect(modal(wrapper).exists()).toBe(true)

    useAuthStore().user = { id: 'u1', username: 'viewer', role: 'viewer', is_active: true } as never
    await flushPromises()

    expect(button(wrapper).exists()).toBe(false)
    expect(modal(wrapper).exists()).toBe(false)
  })
})

describe('AuditSettingsButton.vue — поведение', () => {
  it('по клику открывает форму и читает настройки; окно закрывается событием close', async () => {
    asUser('admin')
    const api = stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const wrapper = mount(AuditSettingsButton)
    expect(modal(wrapper).exists()).toBe(false)

    await button(wrapper).trigger('click')
    await flushPromises()

    expect(modal(wrapper).exists()).toBe(true)
    expect(api.requests).toEqual(['GET /api/v1/audit-log/settings'])

    await wrapper.find('.modal-foot .btn-secondary').trigger('click')
    expect(modal(wrapper).exists()).toBe(false)
  })

  it('после сохранения сообщает родителю итог (экран журнала по нему перечитывает страницу)', async () => {
    asUser('admin')
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    stubAuditSettingsApi({}, { removedNow: 3 })
    const wrapper = mount(AuditSettingsButton)
    await button(wrapper).trigger('click')
    await flushPromises()

    await wrapper.find('[data-field="retention-days"]').setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')?.[0][0]).toMatchObject({ retention_days: 30, removed_now: 3 })
    expect(modal(wrapper).exists()).toBe(false)
  })
})
