// Кнопка «Настройки аудита» на экране «Журнал аудита»: права, перечитывание журнала после сохранения и подпись раздела записей
// об изменении настроек и об очистке. Сама форма проверена в components/__tests__/AuditSettingsModal.spec.ts.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditLogView from '../AuditLogView.vue'
import { useAuthStore } from '../../stores/auth'
import { useCatalogsStore } from '../../stores/catalogs'
import { auditJournal, auditServer } from '../../stores/__tests__/fixtures'
import { BASE_AUDIT_SETTINGS } from '../../stores/__tests__/auditSettingsApi'
import type { AuditLogEntry } from '../../api/types'

let urls: string[]
const pageRequests = () => urls.filter((u) => /\/api\/v1\/audit-log\?/.test(u)).length

function serve(journal: AuditLogEntry[]) {
  const server = auditServer(journal)
  urls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      urls.push(url)
      if (url.includes('/audit-log/settings')) {
        const saved = init?.method === 'PUT'
        return new Response(
          JSON.stringify(
            saved ? { ...BASE_AUDIT_SETTINGS, retention_days: 30, is_default: false, removed_now: 5, cleanup_failed: false } : BASE_AUDIT_SETTINGS,
          ),
        )
      }
      return new Response(JSON.stringify(server(url)))
    }),
  )
}

async function mountView(journal = auditJournal(5)) {
  serve(journal)
  useCatalogsStore().loaded = true
  const wrapper = mount(AuditLogView)
  await flushPromises()
  return wrapper
}

const openButton = (w: Awaited<ReturnType<typeof mountView>>) => w.find('.filter-bar [data-testid="audit-settings-open"]')

function asUser(role: 'admin' | 'viewer') {
  const auth = useAuthStore()
  auth.enabled = true
  auth.initialized = true
  auth.user = { id: 'u1', username: role, role, is_active: true } as never
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('AuditLogView.vue — кнопка «Настройки аудита»', () => {
  it('администратор видит кнопку рядом с «Обновить»', async () => {
    asUser('admin')
    const wrapper = await mountView()

    expect(openButton(wrapper).text()).toBe('Настройки аудита')
    const labels = wrapper.findAll('.filter-bar > .btn').map((b) => b.text())
    expect(labels).toEqual(['Настройки аудита', 'Обновить'])
  })

  it('при выключенной аутентификации кнопка есть', async () => {
    expect(openButton(await mountView()).exists()).toBe(true)
  })

  it('у наблюдателя (viewer) кнопки нет — даже если экран каким-то образом смонтирован', async () => {
    asUser('viewer')
    const wrapper = await mountView()

    expect(openButton(wrapper).exists()).toBe(false)
    expect(urls.some((u) => u.includes('/audit-log/settings'))).toBe(false)
  })

  it('кнопка открывает форму настроек со сроком хранения', async () => {
    asUser('admin')
    const wrapper = await mountView()

    await openButton(wrapper).trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="audit-settings-modal"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="retention-days"]').exists()).toBe(true)
  })

  it('после сохранения настроек журнал перечитывается: в нём появилась запись об изменении, а старые записи могли быть удалены', async () => {
    asUser('admin')
    const wrapper = await mountView()
    const before = pageRequests()

    await openButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.find('[data-field="retention-days"]').setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(pageRequests()).toBe(before + 1)
    expect(wrapper.find('[data-testid="audit-settings-modal"]').exists()).toBe(false)
  })

  it('записи об изменении настроек и об очистке подписаны «Настройки аудита», а не служебным ключом раздела', async () => {
    const service: AuditLogEntry = {
      id: 'svc-1',
      entity_type: 'audit-settings',
      entity_id: 'singleton',
      action: 'DELETE',
      details: 'Очистка журнала по сроку хранения (30 дн.): удалено записей — 5',
      created_at: '2026-11-15T10:00:00',
      actor_id: null,
      actor_username: 'система',
      actor_ip: null,
    }
    const wrapper = await mountView([service, ...auditJournal(3)])

    const row = wrapper.findAll('tbody tr').find((r) => r.text().includes('Очистка журнала'))!
    expect(row.text()).toContain('Настройки аудита')
    expect(row.text()).not.toContain('audit-settings')
    expect(wrapper.findAll('select.fbtn option').map((o) => o.text())).toContain('Настройки аудита')
  })
})
