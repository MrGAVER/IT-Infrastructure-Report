<script setup lang="ts">
// Управление аутентификацией — доступно, пока тумблер выключен (открытый bootstrap, см.
// backend/app/services/auth.set_auth_enabled) ЛИБО текущему пользователю с ролью admin.
// Остальным (viewer при включённой аутентификации) показываем только статус, без форм —
// сервер всё равно отклонит эти запросы (require_admin), но незачем рисовать элементы,
// которые гарантированно приведут к 403.
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, ErrorCode, getStoredSetupToken, setStoredSetupToken } from '../api/client'
import type { UserRole } from '../api/types'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const canManage = computed(() => !auth.enabled || auth.isAdmin)

const toggling = ref(false)
const toggleError = ref<string | null>(null)

const newUser = reactive({ username: '', password: '', role: 'viewer' as UserRole })
const creating = ref(false)
const createError = ref<string | null>(null)

const busyUserId = ref<string | null>(null)
const userActionError = ref<string | null>(null)

// Первичная настройка при выключенной аутентификации разрешена только с localhost или по токену
// установки (backend/app/services/auth.py:require_setup_access) — с другого компьютера сервер отвечает
// 403 SETUP_ACCESS_DENIED, и панель просит ввести токен.
const setupTokenNeeded = ref(false)
const setupTokenInput = ref(getStoredSetupToken() ?? '')

function noteSetupDenied(err: unknown): boolean {
  if (err instanceof ApiError && err.code === ErrorCode.SETUP_ACCESS_DENIED) {
    setupTokenNeeded.value = true
    return true
  }
  return false
}

async function loadUsers() {
  try {
    await auth.fetchUsers()
    setupTokenNeeded.value = false
  } catch (err) {
    if (!noteSetupDenied(err)) userActionError.value = err instanceof ApiError ? err.message : 'Не удалось загрузить пользователей'
  }
}

async function applySetupToken() {
  setStoredSetupToken(setupTokenInput.value.trim() || null)
  userActionError.value = null
  await loadUsers()
}

onMounted(() => {
  if (canManage.value) void loadUsers()
})

async function toggleAuth() {
  const next = !auth.enabled
  if (next) {
    if (!auth.users.some((u) => u.role === 'admin' && u.is_active)) {
      toggleError.value = 'Сначала создайте хотя бы одного активного пользователя с ролью «Администратор».'
      return
    }
  } else if (!confirm('Выключить аутентификацию? Реестр снова станет доступен без входа всем, у кого есть доступ к приложению.')) {
    return
  }
  toggling.value = true
  toggleError.value = null
  try {
    await auth.setEnabled(next)
  } catch (err) {
    noteSetupDenied(err)
    toggleError.value = err instanceof ApiError ? err.message : 'Не удалось изменить настройку'
  } finally {
    toggling.value = false
  }
}

async function createUser() {
  createError.value = null
  if (!newUser.username.trim() || !newUser.password) {
    createError.value = 'Укажите имя пользователя и пароль.'
    return
  }
  creating.value = true
  try {
    await auth.createUser(newUser.username.trim(), newUser.password, newUser.role)
    newUser.username = ''
    newUser.password = ''
    newUser.role = 'viewer'
  } catch (err) {
    noteSetupDenied(err)
    createError.value = err instanceof ApiError ? err.message : 'Не удалось создать пользователя'
  } finally {
    creating.value = false
  }
}

async function toggleRole(id: string, role: UserRole) {
  busyUserId.value = id
  userActionError.value = null
  try {
    await auth.updateUser(id, { role })
  } catch (err) {
    userActionError.value = err instanceof ApiError ? err.message : 'Не удалось изменить роль'
  } finally {
    busyUserId.value = null
  }
}

async function toggleActive(id: string, isActive: boolean) {
  busyUserId.value = id
  userActionError.value = null
  try {
    await auth.updateUser(id, { is_active: isActive })
  } catch (err) {
    userActionError.value = err instanceof ApiError ? err.message : 'Не удалось изменить статус'
  } finally {
    busyUserId.value = null
  }
}

async function removeUser(id: string, username: string) {
  if (!confirm(`Удалить пользователя «${username}»? Действие необратимо.`)) return
  busyUserId.value = id
  userActionError.value = null
  try {
    await auth.deleteUser(id)
  } catch (err) {
    userActionError.value = err instanceof ApiError ? err.message : 'Не удалось удалить пользователя'
  } finally {
    busyUserId.value = null
  }
}
</script>

<template>
  <section class="card section">
    <h2>Аутентификация</h2>
    <p class="hint">
      По умолчанию выключена — однопользовательский локальный режим, реестр открыт без входа (как и до появления этой настройки). Включите, если с приложением
      работает несколько человек и нужно разграничить, кто может только смотреть, а кто — вносить изменения.
    </p>

    <div class="auth-status">
      <span class="status" :class="auth.enabled ? 'on' : 'off'"> <span class="status-dot"></span>{{ auth.enabled ? 'Включена' : 'Выключена' }} </span>
      <button v-if="canManage" type="button" class="btn btn-secondary" :disabled="toggling" @click="toggleAuth">
        {{ auth.enabled ? 'Выключить' : 'Включить' }}
      </button>
    </div>
    <p v-if="toggleError" class="form-error">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>{{ toggleError }}
    </p>

    <template v-if="canManage">
      <form v-if="setupTokenNeeded" class="setup-token-row" @submit.prevent="applySetupToken">
        <p class="hint">
          Настройка доступа с этого компьютера требует токен установки — значение переменной
          <code>INFRA_REGISTRY_SETUP_TOKEN</code> на сервере. Либо откройте приложение на самом сервере (localhost) — там токен не нужен.
        </p>
        <input v-model="setupTokenInput" type="password" placeholder="Токен установки" autocomplete="off" aria-label="Токен установки" />
        <button type="submit" class="btn btn-secondary">Применить</button>
      </form>
      <h3>Пользователи</h3>
      <table v-if="auth.users.length" class="users-table">
        <thead>
          <tr>
            <th>Имя</th>
            <th>Роль</th>
            <th>Статус</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in auth.users" :key="u.id">
            <td>{{ u.username }}<span v-if="u.locked" class="locked-badge" title="Временно заблокирован после неудачных попыток входа">заблокирован</span></td>
            <td>
              <select :value="u.role" :disabled="busyUserId === u.id" @change="toggleRole(u.id, ($event.target as HTMLSelectElement).value as UserRole)">
                <option value="admin">Администратор</option>
                <option value="viewer">Только просмотр</option>
              </select>
            </td>
            <td>
              <button type="button" class="btn btn-secondary btn-sm" :disabled="busyUserId === u.id" @click="toggleActive(u.id, !u.is_active)">
                {{ u.is_active ? 'Активен' : 'Деактивирован' }}
              </button>
            </td>
            <td>
              <button type="button" class="icon-btn" aria-label="Удалить" :disabled="busyUserId === u.id" @click="removeUser(u.id, u.username)">
                <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="userActionError" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>{{ userActionError }}
      </p>

      <form class="new-user-row" @submit.prevent="createUser">
        <input v-model.trim="newUser.username" type="text" placeholder="Имя пользователя" maxlength="150" autocomplete="off" />
        <input v-model="newUser.password" type="password" placeholder="Пароль (мин. 8 символов, буквы и цифры)" autocomplete="new-password" />
        <select v-model="newUser.role">
          <option value="viewer">Только просмотр</option>
          <option value="admin">Администратор</option>
        </select>
        <button type="submit" class="btn btn-primary" :disabled="creating">Добавить</button>
      </form>
      <p v-if="createError" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>{{ createError }}
      </p>
    </template>
    <p v-else class="hint">
      Вы вошли как «{{ auth.user?.username }}» (роль: только просмотр). Управление пользователями и переключателем доступно администраторам.
    </p>
  </section>
</template>

<style scoped>
.section h3 {
  font-family: var(--font-display);
  font-size: 13px;
  margin: 18px 0 10px;
}
.auth-status {
  display: flex;
  align-items: center;
  gap: 12px;
}
.status.on {
  color: var(--status-ok, #33c9a7);
}
.status.off {
  color: var(--ink-muted);
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 8px 11px;
  font-size: 12.5px;
  margin-top: 10px;
}
.users-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.users-table th {
  text-align: left;
  color: var(--ink-muted);
  font-weight: 600;
  font-size: 11px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.users-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.users-table select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 7px;
  color: var(--ink);
  font-family: inherit;
  font-size: 12px;
}
.btn-sm {
  padding: 5px 9px;
  font-size: 11.5px;
}
.locked-badge {
  margin-left: 8px;
  font-size: 10.5px;
  color: var(--status-crit);
  border: 1px solid currentColor;
  border-radius: var(--r-s);
  padding: 1px 5px;
}
.setup-token-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}
.setup-token-row .hint {
  flex-basis: 100%;
  margin: 0;
}
.setup-token-row input {
  flex: 1;
  min-width: 160px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.new-user-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}
.new-user-row input {
  flex: 1;
  min-width: 160px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.new-user-row select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  color: var(--ink);
  font-family: inherit;
  font-size: 12.5px;
}
</style>
