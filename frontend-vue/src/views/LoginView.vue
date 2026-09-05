<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

// Форма — не модалка, поэтому не переиспользует useOverlayDismiss (закрывать тут нечего,
// это единственный экран, который видит непрошедший аутентификацию пользователь).
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const form = reactive({ username: '', password: '' })
const submitting = ref(false)
const errorMessage = ref<string | null>(null)

async function submit() {
  if (!form.username.trim() || !form.password) {
    errorMessage.value = 'Введите имя пользователя и пароль.'
    return
  }
  submitting.value = true
  errorMessage.value = null
  try {
    const ok = await auth.login(form.username.trim(), form.password)
    if (!ok) {
      errorMessage.value = auth.error ?? 'Не удалось войти.'
      return
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <form class="card login-card" @submit.prevent="submit">
      <div class="login-head">
        <span class="login-badge"><svg class="icon"><use href="/icons.svg#i-lock" /></svg></span>
        <h1>РИС</h1>
        <p>Реестр ИТ-инфраструктуры — вход в систему</p>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <label class="field">
        <span>Имя пользователя</span>
        <input v-model.trim="form.username" type="text" autocomplete="username" autofocus required />
      </label>
      <label class="field">
        <span>Пароль</span>
        <input v-model="form.password" type="password" autocomplete="current-password" required />
      </label>

      <button type="submit" class="btn btn-primary login-submit" :disabled="submitting">
        {{ submitting ? 'Входим…' : 'Войти' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-screen {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg);
}
.login-card {
  width: 100%;
  max-width: 360px;
  padding: 28px 26px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.login-head {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 6px;
  margin-bottom: 4px;
}
.login-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--r-m);
  background: var(--surface-2);
  color: var(--brand);
  margin-bottom: 4px;
}
.login-head h1 {
  font-family: var(--font-display);
  font-size: 20px;
  margin: 0;
}
.login-head p {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0;
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 9px 10px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  box-sizing: border-box;
}
.login-submit {
  justify-content: center;
  margin-top: 6px;
  padding: 10px 13px;
}
</style>
