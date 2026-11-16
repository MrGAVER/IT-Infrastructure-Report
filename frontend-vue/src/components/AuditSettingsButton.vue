<script setup lang="ts">
// Кнопка «Настройки аудита» + окно с формой (AuditSettingsModal.vue). Одна и та же кнопка стоит на экране «Журнал аудита» и в
// «Настройках»: компонент один, поэтому права и поведение у них не разойдутся.
//
// Права: кнопка есть только у того, кому доступен сам журнал (auth.canViewAuditLog: администратор, а пока аутентификация
// выключена — единственный пользователь). У viewer её нет вовсе; сервер при этом всё равно отвечает 403 на настройки аудита.
import { ref } from 'vue'
import type { AuditSettingsSaveResult } from '../api/types'
import { useAuthStore } from '../stores/auth'
import AuditSettingsModal from './AuditSettingsModal.vue'

const emit = defineEmits<{ saved: [result: AuditSettingsSaveResult] }>()

const auth = useAuthStore()
const open = ref(false)
</script>

<template>
  <template v-if="auth.canViewAuditLog">
    <button type="button" class="btn btn-secondary" data-testid="audit-settings-open" @click="open = true">
      <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
      Настройки аудита
    </button>
    <AuditSettingsModal v-if="open" @close="open = false" @saved="(result) => emit('saved', result)" />
  </template>
</template>
