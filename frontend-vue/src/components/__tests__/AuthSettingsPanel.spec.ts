import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuthSettingsPanel from '../AuthSettingsPanel.vue'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const viewerUser = {
  id: 'u2',
  username: 'viewer1',
  role: 'viewer',
  is_active: true,
  last_login_at: null,
  locked: false,
  created_at: '2026-01-01T00:00:00',
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})

describe('AuthSettingsPanel.vue', () => {
  it('пока аутентификация выключена, показывает список пользователей и форму создания', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()

    expect(wrapper.text()).toContain('Выключена')
    expect(wrapper.find('.new-user-row').exists()).toBe(true)
  })

  it('не даёт включить аутентификацию, если ни одного активного администратора ещё нет', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([viewerUser])),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()

    await wrapper.find('.auth-status button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('хотя бы одного активного пользователя с ролью «Администратор»')
  })

  it('создаёт пользователя через форму и добавляет его в список', async () => {
    const created = { id: 'u3', username: 'newadmin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/users') && init?.method === 'POST') return jsonResponse(created, 201)
        return jsonResponse([])
      }),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()

    await wrapper.find('.new-user-row input[type="text"]').setValue('newadmin')
    await wrapper.find('.new-user-row input[type="password"]').setValue('Admin1234')
    await wrapper.find('.new-user-row select').setValue('admin')
    await wrapper.find('.new-user-row').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('newadmin')
  })

  it('показывает сообщение сервера при дублирующемся имени пользователя', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/users') && init?.method === 'POST') {
          return jsonResponse({ detail: { message: 'Пользователь «admin» уже существует.', code: 'DUPLICATE_USERNAME' } }, 409)
        }
        return jsonResponse([])
      }),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()

    await wrapper.find('.new-user-row input[type="text"]').setValue('admin')
    await wrapper.find('.new-user-row input[type="password"]').setValue('Admin1234')
    await wrapper.find('.new-user-row').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('уже существует')
  })

  it('при отказе в первичной настройке (403 SETUP_ACCESS_DENIED) просит токен установки и повторяет запрос с ним', async () => {
    const calls: Array<{ url: string; headers: Headers }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const headers = new Headers(init?.headers) // клиент отдаёт fetch объект Headers (B-11)
        calls.push({ url, headers })
        if (headers.get('X-Setup-Token') === 's3cret') return jsonResponse([viewerUser])
        return jsonResponse({ detail: { code: 'SETUP_ACCESS_DENIED', message: 'Первичная настройка только с localhost' } }, 403)
      }),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()

    expect(wrapper.find('.setup-token-row').exists()).toBe(true)
    expect(calls[0].headers.get('X-Setup-Token')).toBeNull()

    await wrapper.find('.setup-token-row input').setValue('s3cret')
    await wrapper.find('.setup-token-row').trigger('submit')
    await flushPromises()

    expect(sessionStorage.getItem('itr:setup-token')).toBe('s3cret')
    expect(wrapper.find('.setup-token-row').exists()).toBe(false)
    expect(wrapper.text()).toContain('viewer1')
  })

  it('не показывает поле токена, если список пользователей загрузился', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([viewerUser])),
    )
    const wrapper = mount(AuthSettingsPanel)
    await flushPromises()
    expect(wrapper.find('.setup-token-row').exists()).toBe(false)
  })
})
