<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AccountPanel from '../components/AccountPanel.vue'
import AuthSettingsPanel from '../components/AuthSettingsPanel.vue'
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { useAuthStore } from '../stores/auth'
import { useThemeStore, COLOR_SCHEMES } from '../stores/theme'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../stores/organization'
import { useFormPreferencesStore } from '../stores/formPreferences'
import { usePreferencesStore } from '../stores/preferences'
import { DEFAULT_COLLAPSE_ROWS, MAX_COLLAPSE_ROWS, MIN_COLLAPSE_ROWS, isValidCollapseLimit } from '../utils/collapseLimit'

const theme = useThemeStore()
const organization = useOrganizationStore()
const auth = useAuthStore()
const formPreferences = useFormPreferencesStore()
const preferences = usePreferencesStore()

// Личные настройки (схема, порог сворачивания, размеры страниц) хранятся на сервере, если есть учётная запись,
// и в этом браузере, если аутентификация выключена, — подпись говорит, где именно, чтобы не вводить в заблуждение.
const personalStorageNote = computed(() =>
  preferences.userStorage === 'local'
    ? 'Личная настройка: аутентификация выключена, поэтому хранится в этом браузере.'
    : 'Личная настройка: хранится на сервере и одинакова на всех ваших компьютерах.',
)

// Название организации общее для всех пользователей: при включённой аутентификации его меняет только
// администратор (сервер ответил бы 403), поэтому остальным поле показывается, но недоступно для правки.
const canEditOrganization = computed(() => !auth.enabled || auth.isAdmin)

// Локальный черновик, а не прямой v-model на organization.name — иначе каждое нажатие клавиши
// тут же переписывало бы шапку сайдбара (и отправляло запрос на сервер) посимвольно; сохраняем осознанным
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

// Общий порог сворачивания длинных списков («VLAN устройства», «Открытые порты»): тоже локальный черновик
// с явным «Сохранить» — недопустимое значение не подменяется молча, а показывается ошибкой под полем.
const draftCollapseLimit = ref(String(formPreferences.collapseRows))
const collapseLimitError = ref('')
const collapseLimitSaved = ref(false)
watch(
  () => formPreferences.collapseRows,
  (value) => {
    draftCollapseLimit.value = String(value)
  },
)

function saveCollapseLimit() {
  collapseLimitSaved.value = false
  if (!isValidCollapseLimit(draftCollapseLimit.value)) {
    collapseLimitError.value = `Укажите целое число от ${MIN_COLLAPSE_ROWS} до ${MAX_COLLAPSE_ROWS}.`
    return
  }
  collapseLimitError.value = ''
  formPreferences.setCollapseRows(draftCollapseLimit.value)
  collapseLimitSaved.value = true
  setTimeout(() => (collapseLimitSaved.value = false), 2000)
}

function resetCollapseLimit() {
  collapseLimitError.value = ''
  formPreferences.reset()
  draftCollapseLimit.value = String(formPreferences.collapseRows)
}
</script>

<template>
  <div class="settings-view">
    <section class="card section">
      <h2>Наименование организации</h2>
      <p class="hint">
        Отображается в шапке слева, под названием реестра. Общее для всех пользователей и хранится на сервере. По умолчанию — «{{ DEFAULT_ORGANIZATION_NAME }}».
      </p>
      <div class="org-name-row">
        <input
          v-model.trim="draftName"
          type="text"
          maxlength="200"
          placeholder="Наименование организации"
          :disabled="!canEditOrganization"
          @keyup.enter="save"
        />
        <button type="button" class="btn btn-primary" :disabled="!canEditOrganization" @click="save">Сохранить</button>
        <button type="button" class="btn btn-secondary" :disabled="!canEditOrganization" @click="resetToDefault">Сбросить</button>
      </div>
      <p v-if="!canEditOrganization" class="hint" data-testid="org-readonly-hint">Менять наименование организации может только администратор.</p>
      <p v-if="saved" class="current">Сохранено.</p>
    </section>

    <section class="card section" data-testid="forms-settings">
      <h2>Формы</h2>
      <p class="hint">
        Длинные списки в форме физического устройства — блок «VLAN устройства» и «Открытые порты» — сворачиваются, когда в них больше указанного количества
        строк (порог общий для обоих). Развернуть список можно кнопкой в его заголовке. По умолчанию — {{ DEFAULT_COLLAPSE_ROWS }}.
      </p>
      <p class="hint" data-testid="personal-storage-note">{{ personalStorageNote }}</p>
      <div class="collapse-limit-row">
        <label for="collapse-rows">Сворачивать списки при количестве строк больше</label>
        <input
          id="collapse-rows"
          v-model="draftCollapseLimit"
          type="number"
          inputmode="numeric"
          :min="MIN_COLLAPSE_ROWS"
          :max="MAX_COLLAPSE_ROWS"
          step="1"
          @keyup.enter="saveCollapseLimit"
        />
        <button type="button" class="btn btn-primary" data-testid="collapse-limit-save" @click="saveCollapseLimit">Сохранить</button>
        <button type="button" class="btn btn-secondary" data-testid="collapse-limit-reset" @click="resetCollapseLimit">Сбросить</button>
      </div>
      <p v-if="collapseLimitError" class="field-error" role="alert" data-testid="collapse-limit-error">{{ collapseLimitError }}</p>
      <p v-else-if="collapseLimitSaved" class="current" data-testid="collapse-limit-saved">Сохранено.</p>
    </section>

    <section class="card section">
      <h2>Цветовая схема</h2>
      <p class="hint">
        Приложение — рабочий инструмент дежурного инженера («Диспетчерская»), поэтому фон и поверхности остаются тёмными во всех схемах. Меняется только
        фирменный акцент — цвета статусов (норма / внимание / тревога) не зависят от выбора и остаются узнаваемыми.
      </p>
      <p class="hint">{{ personalStorageNote }}</p>
      <ThemeSwitcher />
      <p class="current">
        Сейчас выбрано: <strong>{{ theme.scheme.name }}</strong>
      </p>
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
.collapse-limit-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
/* Подпись — гибкая (flex-basis 200px, может расти и переноситься по строкам), а поле и кнопки не сжимаются. Раньше подпись
 * занимала всю свою ширину в одну строку, и в карточке 640px кнопка «Сбросить» уходила под поле одна. Теперь на десктопе
 * всё в одной строке, а в узкой карточке подпись остаётся сверху, и поле с обеими кнопками переносятся вместе. */
.collapse-limit-row label {
  flex: 1 1 200px;
  min-width: 0;
  font-size: 12.5px;
  color: var(--ink);
}
.collapse-limit-row input,
.collapse-limit-row .btn {
  flex: none;
}
.collapse-limit-row input {
  width: 90px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.field-error {
  font-size: 12.5px;
  color: var(--status-crit);
  margin: 10px 0 0;
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
