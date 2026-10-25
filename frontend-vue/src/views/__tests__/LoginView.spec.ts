import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
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

  it.each([
    ['адрес без схемы', '//evil.example'],
    ['абсолютный адрес', 'https://evil.example'],
    ['экран входа (цикл «вход → вход»)', '/login'],
    ['слишком длинная строка', '/' + 'a'.repeat(600)],
  ])('небезопасный ?redirect= (%s) заменяется на дашборд', async (_title, redirect) => {
    routeQuery = { redirect }
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      token: 'tok-1',
      user: { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' },
    })))
    const wrapper = mount(LoginView)

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('Admin1234')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(replaceMock).toHaveBeenCalledTimes(1)
    expect(replaceMock).toHaveBeenCalledWith('/dashboard')
  })

  it('адрес возврата с query-параметрами сохраняется целиком', async () => {
    routeQuery = { redirect: '/devices?x=1' }
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      token: 'tok-1',
      user: { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' },
    })))
    const wrapper = mount(LoginView)

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('Admin1234')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(replaceMock).toHaveBeenCalledWith('/devices?x=1')
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

describe('LoginView.vue — коды ошибок входа (B-12)', () => {
  const tooManyAttempts = (retryAfter?: string) =>
    new Response(
      JSON.stringify({ detail: { code: 'TOO_MANY_ATTEMPTS', message: 'Слишком много неудачных попыток входа. Повторите через 7 с.' } }),
      { status: 429, headers: retryAfter ? { 'Retry-After': retryAfter } : {} },
    )

  async function submitCredentials(wrapper: ReturnType<typeof mount>) {
    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('wrong-pass')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }

  afterEach(() => {
    vi.useRealTimers()
  })

  it('429 с Retry-After: 7 → кнопка отключена, виден текст про 7 с; обратный отсчёт идёт и по окончании разблокирует форму', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    vi.stubGlobal('fetch', vi.fn(async () => tooManyAttempts('7')))
    const wrapper = mount(LoginView)

    await submitCredentials(wrapper)

    const button = wrapper.find('button[type="submit"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="login-throttle"]').text()).toContain('Повторите через 7 с')
    expect(button.text()).toContain('7 с')

    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.find('[data-testid="login-throttle"]').text()).toContain('Повторите через 4 с')
    expect(button.attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(4000)
    expect(wrapper.find('[data-testid="login-throttle"]').exists()).toBe(false)
    expect(wrapper.find('.form-error').exists()).toBe(false)
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.text()).toBe('Войти')
    expect(vi.getTimerCount()).toBe(0) // интервал снят
  })

  it('пока идёт блокировка, отправка формы в обход кнопки (Enter) запросов не делает', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const fetchMock = vi.fn(async () => tooManyAttempts('30'))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(LoginView)
    await submitCredentials(wrapper)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('429 без Retry-After: показано сообщение сервера, отсчёта и блокировки нет', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => tooManyAttempts()))
    const wrapper = mount(LoginView)

    await submitCredentials(wrapper)

    expect(wrapper.find('[data-testid="login-throttle"]').exists()).toBe(false)
    expect(wrapper.find('.form-error').text()).toContain('Слишком много неудачных попыток входа')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('уход с экрана во время отсчёта снимает таймер', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    vi.stubGlobal('fetch', vi.fn(async () => tooManyAttempts('30')))
    const wrapper = mount(LoginView)
    await submitCredentials(wrapper)
    expect(vi.getTimerCount()).toBe(1)

    wrapper.unmount()

    expect(vi.getTimerCount()).toBe(0)
  })

  it('403 CLIENT_NOT_ALLOWED: сообщение сервера и пояснение, что повтор не поможет; кнопка не блокируется', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: { code: 'CLIENT_NOT_ALLOWED', message: 'Доступ с этого адреса запрещён настройками приложения.' } }),
      { status: 403 },
    )))
    const wrapper = mount(LoginView)

    await submitCredentials(wrapper)

    expect(wrapper.find('.form-error').text()).toContain('Доступ с этого адреса запрещён')
    expect(wrapper.find('.form-error').text()).toContain('адрес должен разрешить администратор')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('обычная ошибка входа (401) без пояснения про адрес и без отсчёта', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Неверное имя пользователя или пароль.' }, 401)))
    const wrapper = mount(LoginView)

    await submitCredentials(wrapper)

    expect(wrapper.find('.form-error').text()).toContain('Неверное имя пользователя или пароль')
    expect(wrapper.find('.form-error').text()).not.toContain('администратор')
    expect(wrapper.find('[data-testid="login-throttle"]').exists()).toBe(false)
  })
})

