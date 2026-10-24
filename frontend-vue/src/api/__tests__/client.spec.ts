import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api, UNAUTHORIZED_EVENT } from '../client'

function jsonResponse(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), { status })
}

describe('api/client: ответ 401 и событие UNAUTHORIZED_EVENT', () => {
  const onUnauthorized = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    onUnauthorized.mockClear()
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  })

  afterEach(() => {
    window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  })

  it('401 на PUT /auth/me/password (неверный текущий пароль) НЕ завершает сессию, ошибка пробрасывается', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Текущий пароль указан неверно.' }, 401)))

    await expect(api.put('/auth/me/password', { current_password: 'x', new_password: 'y' })).rejects.toMatchObject({
      status: 401,
      message: 'Текущий пароль указан неверно.',
    })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('401 на POST /auth/login (неверный пароль при входе) тоже не отправляет событие', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Неверное имя пользователя или пароль.' }, 401)))

    await expect(api.post('/auth/login', { username: 'a', password: 'b' })).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it.each(['/auth/me', '/resources/devices', '/devices'])(
    '401 на GET %s (протухший токен) отправляет UNAUTHORIZED_EVENT',
    async (path) => {
      vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Требуется вход.' }, 401)))

      await expect(api.get(path)).rejects.toMatchObject({ status: 401 })
      expect(onUnauthorized).toHaveBeenCalledTimes(1)
    },
  )

  it('другие ошибки (403, 500) событие не отправляют', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Недостаточно прав' }, 403)))
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 403 })

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Ошибка' }, 500)))
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 500 })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
