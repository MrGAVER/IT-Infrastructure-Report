// Стор аутентификации. Токен — источник истины в localStorage (см. api/client.ts:
// getStoredToken/setStoredToken), а не только в этом сторе: любой вызов через api.* сам
// подставляет заголовок Authorization из localStorage, стору не нужно прокидывать токен в
// каждый запрос вручную — здесь только пользователь, статус тумблера и управление учётками.
import { defineStore } from 'pinia'
import { ApiError, api, getStoredToken, setStoredToken } from '../api/client'
import type {
  AuthMeResponse,
  AuthSessionInfo,
  AuthStatus,
  AuthUser,
  LoginResponse,
  UserRole,
} from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    enabled: false,
    user: null as AuthUser | null,
    initialized: false,
    loading: false,
    error: null as string | null,
    users: [] as AuthUser[],
    usersLoading: false,
  }),
  getters: {
    /** Можно показывать защищённые экраны: либо тумблер выключен (однопользовательский режим,
     * как до этой фичи), либо есть залогиненный пользователь. */
    isAuthenticated(state): boolean {
      return !state.enabled || state.user !== null
    },
    isAdmin(state): boolean {
      return state.user?.role === 'admin'
    },
    /** Инвертирована относительно isAuthenticated ради читаемости в router-guard'е
     * (router/index.ts) — там нужно именно «требуется ли сейчас показать форму входа». */
    needsLogin(state): boolean {
      return state.enabled && state.user === null
    },
  },
  actions: {
    /** Вызывается один раз на первую навигацию (см. router/index.ts:beforeEach). /auth/status
     * публичен и не требует токена — безопасно вызывать ещё до восстановления сессии. */
    async init() {
      if (this.initialized) return
      const hasToken = Boolean(getStoredToken())
      try {
        const status = await api.get<AuthStatus>('/auth/status')
        this.enabled = status.enabled
        if (status.enabled && hasToken) {
          await this.fetchMe()
        } else if (!status.enabled) {
          // Тумблер сейчас выключен — токен от прошлого включения (если остался) смысла не
          // имеет, а привести к путанице при следующем включении вполне может.
          setStoredToken(null)
        }
      } catch {
        this.enabled = false
      } finally {
        this.initialized = true
      }
    },
    async fetchMe() {
      try {
        const me = await api.get<AuthMeResponse>('/auth/me')
        this.enabled = me.enabled
        this.user = me.user
      } catch {
        this.user = null
        setStoredToken(null)
      }
    },
    async login(username: string, password: string): Promise<boolean> {
      this.loading = true
      this.error = null
      try {
        const result = await api.post<LoginResponse>('/auth/login', { username, password })
        setStoredToken(result.token)
        this.user = result.user
        this.enabled = true
        return true
      } catch (err) {
        this.error = err instanceof ApiError ? err.message : 'Не удалось войти'
        return false
      } finally {
        this.loading = false
      }
    },
    async logout() {
      try {
        await api.post('/auth/logout', {})
      } catch {
        /* даже если запрос не прошёл (например, токен уже истёк) — разлогиниваем локально */
      } finally {
        setStoredToken(null)
        this.user = null
      }
    },
    /** Реакция на глобальное событие UNAUTHORIZED_EVENT (см. api/client.ts) — токен
     * истёк/отозван (logout на другой вкладке, смена пароля администратором и т.п.).
     * Подписка регистрируется в main.ts, не здесь — см. комментарий в client.ts про циклы импорта. */
    handleUnauthorized() {
      setStoredToken(null)
      this.user = null
    },
    async setEnabled(enabled: boolean): Promise<AuthStatus> {
      const result = await api.put<AuthStatus>('/auth/settings', { enabled })
      this.enabled = result.enabled
      return result
    },
    async fetchUsers() {
      this.usersLoading = true
      try {
        this.users = await api.get<AuthUser[]>('/auth/users')
      } finally {
        this.usersLoading = false
      }
    },
    async createUser(username: string, password: string, role: UserRole): Promise<AuthUser> {
      const user = await api.post<AuthUser>('/auth/users', { username, password, role })
      this.users.push(user)
      return user
    },
    async updateUser(
      id: string,
      payload: Partial<{ username: string; password: string; role: UserRole; is_active: boolean }>,
    ): Promise<AuthUser> {
      const updated = await api.put<AuthUser>(`/auth/users/${id}`, payload)
      const idx = this.users.findIndex((u) => u.id === id)
      if (idx !== -1) this.users[idx] = updated
      if (this.user?.id === id) this.user = updated
      return updated
    },
    async deleteUser(id: string) {
      await api.delete(`/auth/users/${id}`)
      this.users = this.users.filter((u) => u.id !== id)
    },
    fetchMySessions() {
      return api.get<AuthSessionInfo[]>('/auth/sessions')
    },
  },
})
