<script setup lang="ts">
// Самообслуживание — доступно ЛЮБОЙ роли (в отличие от AuthSettingsPanel.vue, которая целиком
// про администрирование чужих учёток и сам тумблер). Показывается только когда есть реальная
// сессия — при выключенной аутентификации тут нечего показывать (см. SettingsView.vue).
import { onMounted, reactive, ref } from 'vue'
import { ApiError, ErrorCode } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatServerDateTime } from '../utils/dateTime'
// Общий вид панелей «Настроек»: без него заголовок и подписи панели брали браузерные стили (UI-03).
import '../styles/settings-section.css'

const auth = useAuthStore()

const pwd = reactive({ current: '', next: '', confirm: '' })
const pwdSaving = ref(false)
const pwdError = ref<string | null>(null)
const pwdSaved = ref(false)

const revokingId = ref<string | null>(null)
const sessionsError = ref<string | null>(null)

onMounted(() => {
  void auth.fetchMySessions()
})

async function changePassword() {
  pwdError.value = null
  pwdSaved.value = false
  if (!pwd.current || !pwd.next) {
    pwdError.value = 'Заполните текущий и новый пароль.'
    return
  }
  if (pwd.next !== pwd.confirm) {
    pwdError.value = 'Новый пароль и подтверждение не совпадают.'
    return
  }
  pwdSaving.value = true
  try {
    await auth.changeOwnPassword(pwd.current, pwd.next)
    pwd.current = ''
    pwd.next = ''
    pwd.confirm = ''
    pwdSaved.value = true
    setTimeout(() => (pwdSaved.value = false), 2500)
  } catch (err) {
    pwdError.value = err instanceof ApiError ? err.message : 'Не удалось сменить пароль'
    // Неверный текущий пароль — опечатка, а не конец сессии (сервер отвечает 422 WRONG_CURRENT_PASSWORD): поле очищаем для повторного ввода.
    if (err instanceof ApiError && err.code === ErrorCode.WRONG_CURRENT_PASSWORD) pwd.current = ''
  } finally {
    pwdSaving.value = false
  }
}

async function revoke(id: string) {
  revokingId.value = id
  sessionsError.value = null
  try {
    await auth.revokeSession(id)
  } catch (err) {
    sessionsError.value = err instanceof ApiError ? err.message : 'Не удалось завершить сессию'
  } finally {
    revokingId.value = null
  }
}
</script>

<template>
  <section class="card settings-section">
    <h2>Моя учётная запись</h2>
    <p class="hint">Вы вошли как «{{ auth.user?.username }}» ({{ auth.isAdmin ? 'администратор' : 'только просмотр' }}).</p>

    <h3>Сменить пароль</h3>
    <form class="pwd-form" @submit.prevent="changePassword">
      <label class="field">
        <span>Текущий пароль</span>
        <input v-model="pwd.current" type="password" autocomplete="current-password" />
      </label>
      <label class="field">
        <span>Новый пароль</span>
        <input v-model="pwd.next" type="password" autocomplete="new-password" />
      </label>
      <label class="field">
        <span>Повторите новый пароль</span>
        <input v-model="pwd.confirm" type="password" autocomplete="new-password" />
      </label>
      <button type="submit" class="btn btn-primary" :disabled="pwdSaving">
        {{ pwdSaving ? 'Сохранение…' : 'Сменить пароль' }}
      </button>
    </form>
    <p v-if="pwdSaved" class="current">Пароль изменён. Другие ваши сессии завершены — эта осталась активной.</p>
    <p v-if="pwdError" class="form-error">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>{{ pwdError }}
    </p>

    <h3>Мои активные сессии</h3>
    <table v-if="auth.sessions.length" class="sessions-table">
      <thead>
        <tr>
          <th>Начало</th>
          <th>Истекает</th>
          <th>Устройство</th>
          <th>IP</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in auth.sessions" :key="s.id">
          <td>{{ formatServerDateTime(s.created_at) }}</td>
          <td>{{ formatServerDateTime(s.expires_at) }}</td>
          <td class="ua" :title="s.user_agent ?? undefined">{{ s.user_agent ?? '—' }}</td>
          <td>{{ s.ip_address ?? '—' }}</td>
          <td>
            <span v-if="s.current" class="current-badge">эта сессия</span>
            <button v-else type="button" class="btn btn-secondary btn-sm" :disabled="revokingId === s.id" @click="revoke(s.id)">Завершить</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!auth.sessionsLoading" class="hint">Активных сессий не найдено.</p>
    <p v-if="sessionsError" class="form-error">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>{{ sessionsError }}
    </p>
  </section>
</template>

<style scoped>
.pwd-form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field input {
  min-width: 180px;
}
.sessions-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.sessions-table th {
  text-align: left;
  color: var(--ink-muted);
  font-weight: 600;
  font-size: 11px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.sessions-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.sessions-table .ua {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.current-badge {
  font-size: 10.5px;
  color: var(--brand);
  border: 1px solid currentColor;
  border-radius: var(--r-s);
  padding: 2px 7px;
}
.btn-sm {
  padding: 5px 9px;
  font-size: 11.5px;
}
</style>
