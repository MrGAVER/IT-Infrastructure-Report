// B-04: authStore.canWrite — единый источник правды «можно ли менять данные» для интерфейса.
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../auth'
import type { AuthUser } from '../../api/types'

const user = (role: 'admin' | 'viewer'): AuthUser =>
  ({ id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }) as AuthUser

beforeEach(() => setActivePinia(createPinia()))

describe('authStore.canWrite', () => {
  it('аутентификация выключена: один пользователь с полным доступом', () => {
    const auth = useAuthStore()
    auth.enabled = false
    auth.user = null
    expect(auth.canWrite).toBe(true)
  })

  it('аутентификация включена, роль admin — писать можно', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = user('admin')
    expect(auth.canWrite).toBe(true)
  })

  it('аутентификация включена, роль viewer — только чтение', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = user('viewer')
    expect(auth.canWrite).toBe(false)
  })

  it('аутентификация включена, но сессии нет (до входа) — писать нельзя', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = null
    expect(auth.canWrite).toBe(false)
  })

  it('реагирует на смену пользователя без пересоздания стора (вход viewer → выход)', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = user('viewer')
    expect(auth.canWrite).toBe(false)
    auth.user = user('admin')
    expect(auth.canWrite).toBe(true)
  })
})
