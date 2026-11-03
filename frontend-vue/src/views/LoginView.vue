<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ErrorCode } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { safeRedirect } from '../utils/safeRedirect'

// Форма — не модалка, поэтому не переиспользует useOverlayDismiss (закрывать тут нечего,
// это единственный экран, который видит непрошедший аутентификацию пользователь).
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const form = reactive({ username: '', password: '' })
const submitting = ref(false)
const errorMessage = ref<string | null>(null)
// 403 CLIENT_NOT_ALLOWED: адрес не разрешён настройками приложения — это не «неверный пароль», повтор не поможет.
const clientNotAllowed = ref(false)

// 429 TOO_MANY_ATTEMPTS: сервер временно не принимает попытки входа и сообщает паузу в Retry-After.
// Показываем обратный отсчёт и держим кнопку отключённой — иначе пользователь зря долбит форму (а каждая
// попытка за время блокировки только продлевает ожидание в его собственных глазах).
const retryLeft = ref(0)
const locked = computed(() => retryLeft.value > 0)
let retryTimer: ReturnType<typeof setInterval> | null = null

function stopCountdown() {
  if (retryTimer !== null) clearInterval(retryTimer)
  retryTimer = null
}

function startCountdown(seconds: number) {
  stopCountdown()
  retryLeft.value = seconds
  retryTimer = setInterval(() => {
    retryLeft.value -= 1
    if (retryLeft.value <= 0) {
      stopCountdown()
      retryLeft.value = 0
      errorMessage.value = null // пауза закончилась — можно пробовать снова
    }
  }, 1000)
}

onBeforeUnmount(stopCountdown)

async function submit() {
  if (locked.value) return // в обход отключённой кнопки (Enter в поле) попытку не отправляем
  if (!form.username.trim() || !form.password) {
    errorMessage.value = 'Введите имя пользователя и пароль.'
    return
  }
  submitting.value = true
  errorMessage.value = null
  clientNotAllowed.value = false
  try {
    const ok = await auth.login(form.username.trim(), form.password)
    if (!ok) {
      errorMessage.value = auth.error ?? 'Не удалось войти.'
      clientNotAllowed.value = auth.errorCode === ErrorCode.CLIENT_NOT_ALLOWED
      if (auth.errorCode === ErrorCode.TOO_MANY_ATTEMPTS && auth.errorRetryAfter) startCountdown(auth.errorRetryAfter)
      return
    }
    router.replace(safeRedirect(route.query.redirect))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <form class="card login-card" @submit.prevent="submit">
      <div class="login-head">
        <span class="login-badge"
          ><svg class="icon"><use href="/icons.svg#i-lock" /></svg
        ></span>
        <h1>РИС</h1>
        <p>Реестр ИТ-инфраструктуры — вход в систему</p>
      </div>

      <div v-if="locked" class="form-error" role="alert" data-testid="login-throttle">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        Слишком много неудачных попыток входа. Повторите через {{ retryLeft }} с.
      </div>
      <div v-else-if="errorMessage" class="form-error" role="alert">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
        <template v-if="clientNotAllowed"> Повторные попытки не помогут: адрес должен разрешить администратор.</template>
      </div>

      <label class="field">
        <span>Имя пользователя</span>
        <input v-model.trim="form.username" type="text" autocomplete="username" autofocus required />
      </label>
      <label class="field">
        <span>Пароль</span>
        <input v-model="form.password" type="password" autocomplete="current-password" required />
      </label>

      <button type="submit" class="btn btn-primary login-submit" :disabled="submitting || locked">
        {{ submitting ? 'Входим…' : locked ? `Повторите через ${retryLeft} с` : 'Войти' }}
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
  color: var(--crit-ink);
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
