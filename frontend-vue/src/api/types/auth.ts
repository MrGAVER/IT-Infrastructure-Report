// Аутентификация. Часть типов API, см. ./index.ts.

// --- Аутентификация (backend/app/api/auth.py, backend/app/services/auth.serialize_user) --------
// Ровно две роли — см. UserRole в backend/app/constants.py: admin (полный доступ + управление
// пользователями/тумблером) и viewer (только чтение, кроме собственного logout).
export type UserRole = 'admin' | 'viewer'

export interface AuthUser {
  id: string
  username: string
  role: UserRole
  is_active: boolean
  last_login_at: string | null
  locked: boolean
  created_at: string
}

export interface AuthStatus {
  enabled: boolean
  session_ttl_hours: number
}

export interface AuthMeResponse {
  enabled: boolean
  user: AuthUser | null
}

export interface LoginResponse {
  token: string
  user: AuthUser
}

export interface AuthSessionInfo {
  id: string
  created_at: string
  expires_at: string
  user_agent: string | null
  ip_address: string | null
  /** Сессия, которой был выполнен сам запрос GET /auth/sessions (см.
   * backend/app/services/auth.serialize_session) — не бизнес-данные конкретной сессии, а
   * relation to "текущий запрос". */
  current: boolean
}
