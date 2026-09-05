<script setup lang="ts">
import { ref, watch } from 'vue'
import AccountPanel from '../components/AccountPanel.vue'
import AuthSettingsPanel from '../components/AuthSettingsPanel.vue'
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { useAuthStore } from '../stores/auth'
import { useThemeStore, COLOR_SCHEMES } from '../stores/theme'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../stores/organization'

const theme = useThemeStore()
const organization = useOrganizationStore()
const auth = useAuthStore()

// Локальный черновик, а не прямой v-model на organization.name — иначе каждое нажатие клавиши
// тут же переписывало бы шапку сайдбара (и localStorage) посимвольно; сохраняем осознанным
// действием, как и остальные формы в приложении.
const draftName = ref(organization.name)
const saved = ref(false)
watch(
  () => organization.name,
  (name) => {
    draftName.value = name
  },
)

function save() {
  organization.setName(draftName.value)
  draftName.value = organization.name // подхватить нормализацию (trim/fallback на дефолт)
  saved.value = true
  setTimeout(() => (saved.value = false), 2000)
}

function resetToDefault() {
  organization.reset()
}
</script>

<template>
  <div class="settings-view">
    <section class="card section">
      <h2>Наименование организации</h2>
      <p class="hint">Отображается в шапке слева, под названием реестра. По умолчанию — «{{ DEFAULT_ORGANIZATION_NAME }}».</p>
      <div class="org-name-row">
        <input v-model.trim="draftName" type="text" maxlength="255" placeholder="Наименование организации" @keyup.enter="save" />
        <button type="button" class="btn btn-primary" @click="save">Сохранить</button>
        <button type="button" class="btn btn-secondary" @click="resetToDefault">Сбросить</button>
      </div>
      <p v-if="saved" class="current">Сохранено.</p>
    </section>

    <section class="card section">
      <h2>Цветовая схема</h2>
      <p class="hint">
        Приложение — рабочий инструмент дежурного инженера («Диспетчерская»), поэтому фон и
        поверхности остаются тёмными во всех схемах. Меняется только фирменный акцент — цвета
        статусов (норма / внимание / тревога) не зависят от выбора и остаются узнаваемыми.
      </p>
      <ThemeSwitcher />
      <p class="current">Сейчас выбрано: <strong>{{ theme.scheme.name }}</strong></p>
    </section>

    <section class="card section preview">
      <h2>Предпросмотр</h2>
      <div class="preview-row">
        <button class="btn btn-primary">Основная кнопка</button>
        <button class="btn btn-secondary">Второстепенная кнопка</button>
        <span class="status on"><span class="status-dot"></span>SIEM: норма</span>
        <span class="status off"><span class="status-dot"></span>SIEM: внимание</span>
      </div>
      <div class="swatches">
        <div v-for="s in COLOR_SCHEMES" :key="s.id" class="swatch-row">
          <span class="dot" :style="{ background: s.brand }"></span>
          {{ s.name }} — <span class="mono">{{ s.brand }}</span>
        </div>
      </div>
    </section>

    <AuthSettingsPanel />
    <AccountPanel v-if="auth.enabled && auth.user" />
  </div>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 640px;
}
.section {
  padding: 20px 22px;
}
.section h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0 0 10px;
}
.hint {
  font-size: 12.5px;
  color: var(--ink-muted);
  line-height: 1.6;
  margin: 0 0 16px;
}
.current {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin-top: 14px;
}
.org-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.org-name-row input {
  flex: 1;
  min-width: 220px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.preview-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.swatches {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.swatch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
