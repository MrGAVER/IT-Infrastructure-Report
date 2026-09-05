import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LoginView from '../LoginView.vue'

const replaceMock = vi.fn()
let routeQuery: Record<string, string> = {}
vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useRoute: () => ({ query: routeQuery }),
}))

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  replaceMock.mockClear()
  routeQuery = {}
})

describe('LoginView.vue', () => {
  it('не отправляет форму и показывает ошибку, если поля не заполнены', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const wrapper = mount(LoginView)

    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('Введите имя пользователя и пароль')
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('при успешном входе перенаправляет на дашборд по умолчанию', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      token: 'tok-1',
      user: { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' },
    })))
    const wrapper = mount(LoginView)

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('Admin1234')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(replaceMock).toHaveBeenCalledWith('/dashboard')
    expect(localStorage.getItem('itr:auth-token')).toBe('tok-1')
  })

  it('уважает ?redirect= из query-параметра', async () => {
    routeQuery = { redirect: '/devices' }
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      token: 'tok-1',
      user: { id: 'u1', username: 'admin', role: 'viewer', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' },
    })))
    const wrapper = mount(LoginView)

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('Admin1234')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(replaceMock).toHaveBeenCalledWith('/devices')
  })

  it('при неверном пароле показывает сообщение об ошибке и не редиректит', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Неверное имя пользователя или пароль.' }, 401)))
    const wrapper = mount(LoginView)

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('wrong-pass')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Неверное имя пользователя или пароль')
    expect(replaceMock).not.toHaveBeenCalled()
  })
})
