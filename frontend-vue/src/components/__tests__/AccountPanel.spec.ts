import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AccountPanel from '../AccountPanel.vue'
import { UNAUTHORIZED_EVENT } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

function jsonResponse(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), { status })
}

const sessionsFixture = [
  { id: 's1', created_at: '2026-01-01T10:00:00', expires_at: '2026-01-01T22:00:00', user_agent: 'Chrome/Windows', ip_address: '10.0.0.5', current: true },
  { id: 's2', created_at: '2026-01-01T09:00:00', expires_at: '2026-01-01T21:00:00', user_agent: 'Firefox/Linux', ip_address: '10.0.0.9', current: false },
]

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.enabled = true
  auth.user = { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
})

describe('AccountPanel.vue', () => {
  it('загружает и показывает список активных сессий, помечая текущую', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sessionsFixture)),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    expect(wrapper.text()).toContain('Chrome/Windows')
    expect(wrapper.text()).toContain('Firefox/Linux')
    expect(wrapper.text()).toContain('эта сессия')
  })

  it('время сессии без смещения пояса считается UTC и показывается в поясе браузера', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sessionsFixture)),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    // sessionsFixture[0].created_at = '2026-01-01T10:00:00' (naive UTC на сервере)
    const expected = new Date(Date.UTC(2026, 0, 1, 10, 0, 0)).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
    expect(wrapper.findAll('tbody tr')[0].findAll('td')[0].text()).toBe(expected)
  })

  it('не показывает кнопку "Завершить" у текущей сессии', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sessionsFixture)),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows[0].find('button.btn-secondary').exists()).toBe(false)
    expect(rows[1].find('button.btn-secondary').exists()).toBe(true)
  })

  it('завершает другую сессию по клику и убирает её из таблицы', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/sessions/s2') && init?.method === 'DELETE') return jsonResponse(null, 204)
        return jsonResponse(sessionsFixture)
      }),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    await wrapper.findAll('tbody tr')[1].find('button.btn-secondary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Firefox/Linux')
  })

  it('не отправляет форму смены пароля, если новый пароль и подтверждение расходятся', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    const inputs = wrapper.findAll('.pwd-form input')
    await inputs[0].setValue('OldPass1234')
    await inputs[1].setValue('NewPass1234')
    await inputs[2].setValue('Mismatch1234')
    await wrapper.find('.pwd-form').trigger('submit')

    expect(wrapper.text()).toContain('не совпадают')
  })

  it('меняет пароль и показывает подтверждение при успехе', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/me/password') && init?.method === 'PUT') {
          return jsonResponse({
            id: 'u1',
            username: 'admin',
            role: 'admin',
            is_active: true,
            last_login_at: null,
            locked: false,
            created_at: '2026-01-01T00:00:00',
          })
        }
        return jsonResponse([])
      }),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    const inputs = wrapper.findAll('.pwd-form input')
    await inputs[0].setValue('OldPass1234')
    await inputs[1].setValue('NewPass1234')
    await inputs[2].setValue('NewPass1234')
    await wrapper.find('.pwd-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Пароль изменён')
  })

  it('показывает сообщение сервера при неверном текущем пароле', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/me/password') && init?.method === 'PUT') {
          return jsonResponse({ detail: 'Текущий пароль указан неверно.' }, 401)
        }
        return jsonResponse([])
      }),
    )
    const wrapper = mount(AccountPanel)
    await flushPromises()

    const inputs = wrapper.findAll('.pwd-form input')
    await inputs[0].setValue('WrongPass1')
    await inputs[1].setValue('NewPass1234')
    await inputs[2].setValue('NewPass1234')
    await wrapper.find('.pwd-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Текущий пароль указан неверно')
  })

  it('неверный текущий пароль (401) не завершает сессию: форма остаётся, пользователь не сброшен', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/me/password') && init?.method === 'PUT') {
          return jsonResponse({ detail: 'Текущий пароль указан неверно.' }, 401)
        }
        return jsonResponse([])
      }),
    )
    // Подписка как в main.ts: на событие 401 стор сбрасывает локальную сессию.
    const auth = useAuthStore()
    const onUnauthorized = () => auth.handleUnauthorized()
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    try {
      const wrapper = mount(AccountPanel)
      await flushPromises()

      const inputs = wrapper.findAll('.pwd-form input')
      await inputs[0].setValue('WrongPass1')
      await inputs[1].setValue('NewPass1234')
      await inputs[2].setValue('NewPass1234')
      await wrapper.find('.pwd-form').trigger('submit')
      await flushPromises()

      expect(wrapper.find('.pwd-form').exists()).toBe(true)
      expect(wrapper.find('.form-error').text()).toContain('Текущий пароль указан неверно')
      expect(auth.user).not.toBeNull()
      expect(auth.user?.username).toBe('admin')
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  })

  // A-22: сервер отвечает на неверный текущий пароль 422 с кодом WRONG_CURRENT_PASSWORD (а не 401): сессия не завершается.
  it('неверный текущий пароль (422 WRONG_CURRENT_PASSWORD): сообщение сервера, поле текущего пароля очищено, сессия сохранена', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/auth/me/password') && init?.method === 'PUT') {
          return jsonResponse({ detail: { message: 'Текущий пароль указан неверно.', code: 'WRONG_CURRENT_PASSWORD' } }, 422)
        }
        return jsonResponse([])
      }),
    )
    const auth = useAuthStore()
    const onUnauthorized = () => auth.handleUnauthorized()
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    try {
      const wrapper = mount(AccountPanel)
      await flushPromises()

      const inputs = wrapper.findAll('.pwd-form input')
      await inputs[0].setValue('WrongPass1')
      await inputs[1].setValue('NewPass1234')
      await inputs[2].setValue('NewPass1234')
      await wrapper.find('.pwd-form').trigger('submit')
      await flushPromises()

      expect(wrapper.find('.form-error').text()).toContain('Текущий пароль указан неверно')
      expect((wrapper.findAll('.pwd-form input')[0].element as HTMLInputElement).value).toBe('')
      expect((wrapper.findAll('.pwd-form input')[1].element as HTMLInputElement).value).toBe('NewPass1234')
      expect(auth.user).not.toBeNull()
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  })
})
