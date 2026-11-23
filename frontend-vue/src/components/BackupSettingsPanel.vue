<script setup lang="ts">
// Панель «Резервные копии» экрана «Настройки»: интервал и число плановых копий SQLite, статус последней копии. Только администратору
// (auth.canManageBackups; сервер при этом сам отвечает viewer'у 403). Применяется сразу, перезапускать приложение не нужно.
//
// Источник значения (backend/app/services/backup_settings.py): окружение > эта форма > умолчание. Параметр, заданный окружением или
// infra_registry.toml, показывается, но не правится («задано в окружении»). Каталог копий из формы не меняется — его задаёт оператор
// переменной INFRA_REGISTRY_BACKUP_DIR, форма его только показывает. Для PostgreSQL копии делает оператор СУБД: панель лишь подсказывает, где это
// описано.
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import type { BackupSettingsUpdate } from '../api/types'
import { useToast } from '../composables/useToast'
import { useBackupSettingsStore } from '../stores/backupSettings'
import { describeInterval, formatFileSize, parseIntervalHours, parseKeepCount } from '../utils/backupSettings'
import { formatServerDateTime } from '../utils/dateTime'
import '../styles/settings-section.css'

const store = useBackupSettingsStore()
const toast = useToast()

const settings = computed(() => store.settings)
const draftInterval = ref('')
const draftKeep = ref('')
const errorMessage = ref<string | null>(null)
const touched = ref(false)

// Поля заполняются значениями с сервера — из кэша стора и после свежей загрузки, но только пока пользователь ничего не вводил.
watch(
  () => store.settings,
  (value) => {
    if (value && !touched.value) {
      draftInterval.value = String(value.interval_hours)
      draftKeep.value = String(value.keep)
    }
  },
  { immediate: true },
)
watch([draftInterval, draftKeep], () => (errorMessage.value = null))
onMounted(() => void store.load())

const intervalLocked = computed(() => settings.value?.interval_source === 'environment')
const keepLocked = computed(() => settings.value?.keep_source === 'environment')
const parsedInterval = computed(() =>
  settings.value ? parseIntervalHours(draftInterval.value, { min: settings.value.min_interval_hours, max: settings.value.max_interval_hours }) : null,
)
const parsedKeep = computed(() => (settings.value ? parseKeepCount(draftKeep.value, settings.value.max_keep) : null))
// Ошибку заблокированного (заданного окружением) поля не показываем: его значение пользователь не вводит.
const intervalError = computed(() => (!intervalLocked.value && parsedInterval.value && !parsedInterval.value.ok ? parsedInterval.value.error : null))
const keepError = computed(() => (!keepLocked.value && parsedKeep.value && !parsedKeep.value.ok ? parsedKeep.value.error : null))

/** Только действительно изменённые и не заданные окружением параметры; null — поля нечего сохранять или значение некорректно. */
const patch = computed<BackupSettingsUpdate | null>(() => {
  const current = settings.value
  if (!current || intervalError.value || keepError.value) return null
  const result: BackupSettingsUpdate = {}
  if (!intervalLocked.value && parsedInterval.value?.ok && parsedInterval.value.value !== current.interval_hours) {
    result.interval_hours = parsedInterval.value.value
  }
  if (!keepLocked.value && parsedKeep.value?.ok && parsedKeep.value.value !== current.keep) result.keep = parsedKeep.value.value
  return Object.keys(result).length ? result : null
})
const canSave = computed(() => !store.saving && patch.value !== null)

const canReset = computed(() => {
  const current = settings.value
  if (!current || store.saving) return false
  return current.interval_source === 'settings' || current.keep_source === 'settings'
})

function sourceNote(source: string): string {
  return source === 'environment' ? 'задано в окружении' : source === 'settings' ? 'задано в настройках' : 'значение по умолчанию'
}

async function apply(changes: BackupSettingsUpdate, message: string) {
  errorMessage.value = null
  try {
    await store.save(changes)
    touched.value = false
    if (store.settings) {
      draftInterval.value = String(store.settings.interval_hours)
      draftKeep.value = String(store.settings.keep)
    }
    toast.notify(message, 'success')
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Не удалось сохранить настройки резервных копий'
  }
}

function save() {
  const changes = patch.value
  if (!changes || !canSave.value) return
  if (changes.interval_hours === 0 && !confirm('Плановые копии базы будут выключены: пока они выключены, приложение само копии не делает. Продолжить?')) return
  void apply(changes, 'Настройки резервных копий сохранены.')
}

function reset() {
  const current = settings.value
  if (!current) return
  const changes: BackupSettingsUpdate = {}
  if (current.interval_source === 'settings') changes.interval_hours = null
  if (current.keep_source === 'settings') changes.keep = null
  void apply(changes, 'Настройки резервных копий сброшены к значениям по умолчанию.')
}
</script>

<template>
  <section class="card settings-section" data-testid="backup-settings-section">
    <h2>Резервные копии</h2>

    <p v-if="store.error && !settings" class="form-error" role="alert" data-testid="backup-load-error">{{ store.error }}</p>
    <p v-else-if="!settings" class="hint" data-testid="backup-loading">Загрузка настроек…</p>

    <p v-else-if="!settings.supported" class="hint" data-testid="backup-unsupported">
      {{ settings.unsupported_reason }} Периодичность и каталог копий задаются в файле <code>.env</code> и средствами СУБД — см. README, раздел «Периодические
      резервные копии».
    </p>

    <template v-else>
      <p class="hint">
        Приложение само делает копию базы SQLite: при запуске, если копий ещё нет или последняя старше интервала, и затем через каждый интервал; хранится
        указанное число последних копий. Изменения применяются сразу, перезапускать приложение не нужно. 0 в интервале — копии выключены.
      </p>

      <form class="backup-form" @submit.prevent="save">
        <label class="field" for="backup-interval">Интервал между копиями, часов</label>
        <div class="field-row">
          <input
            id="backup-interval"
            v-model="draftInterval"
            type="text"
            inputmode="decimal"
            data-testid="backup-interval"
            :disabled="intervalLocked || store.saving"
            :aria-invalid="intervalError ? 'true' : undefined"
            @input="touched = true"
          />
          <span class="source" data-testid="backup-interval-source">{{ sourceNote(settings.interval_source) }}</span>
        </div>
        <p v-if="intervalError" class="field-error" role="alert" data-testid="backup-interval-error">{{ intervalError }}</p>
        <p v-else-if="intervalLocked" class="hint" data-testid="backup-interval-locked">
          Задано переменной INFRA_REGISTRY_BACKUP_INTERVAL_HOURS (или в infra_registry.toml) и в настройках не меняется.
        </p>

        <label class="field" for="backup-keep">Сколько копий хранить</label>
        <div class="field-row">
          <input
            id="backup-keep"
            v-model="draftKeep"
            type="text"
            inputmode="numeric"
            data-testid="backup-keep"
            :disabled="keepLocked || store.saving"
            :aria-invalid="keepError ? 'true' : undefined"
            @input="touched = true"
          />
          <span class="source" data-testid="backup-keep-source">{{ sourceNote(settings.keep_source) }}</span>
        </div>
        <p v-if="keepError" class="field-error" role="alert" data-testid="backup-keep-error">{{ keepError }}</p>
        <p v-else-if="keepLocked" class="hint" data-testid="backup-keep-locked">
          Задано переменной INFRA_REGISTRY_BACKUP_KEEP (или в infra_registry.toml) и в настройках не меняется.
        </p>

        <div v-if="errorMessage" class="form-error" role="alert" data-testid="backup-save-error">{{ errorMessage }}</div>

        <div class="actions">
          <button type="submit" class="btn btn-primary" data-testid="backup-save" :disabled="!canSave">Сохранить</button>
          <button type="button" class="btn btn-secondary" data-testid="backup-reset" :disabled="!canReset" @click="reset">Сбросить к умолчанию</button>
        </div>
      </form>

      <dl class="status">
        <dt>Сейчас</dt>
        <dd data-testid="backup-current">
          {{ describeInterval(settings.interval_hours) }}, хранить {{ settings.keep }}
          <span v-if="settings.interval_hours > 0 && !settings.running"> (планировщик не запущен — перезапустите приложение)</span>
        </dd>
        <dt>Каталог копий</dt>
        <dd data-testid="backup-directory">
          <code>{{ settings.directory }}</code>
          <span class="source">{{ settings.directory_source === 'environment' ? 'задан в окружении' : 'по умолчанию' }}</span>
          <span class="source">меняется только переменной INFRA_REGISTRY_BACKUP_DIR</span>
        </dd>
        <dt>Последняя копия</dt>
        <dd data-testid="backup-latest">
          <template v-if="settings.latest">
            {{ formatServerDateTime(settings.latest.created_at) }} — <code>{{ settings.latest.name }}</code>, {{ formatFileSize(settings.latest.size_bytes) }}
          </template>
          <template v-else>копий ещё нет</template>
        </dd>
        <dt>Последняя попытка</dt>
        <dd data-testid="backup-last-attempt">
          <template v-if="!settings.last_attempt">с запуска приложения попыток не было</template>
          <template v-else-if="!settings.last_attempt.ok">
            {{ formatServerDateTime(settings.last_attempt.at) }} — <strong class="failed">ошибка:</strong> {{ settings.last_attempt.error }}
          </template>
          <template v-else-if="settings.last_attempt.created">
            {{ formatServerDateTime(settings.last_attempt.at) }} — создана копия <code>{{ settings.last_attempt.created }}</code>
          </template>
          <template v-else>{{ formatServerDateTime(settings.last_attempt.at) }} — копия не понадобилась: база не менялась</template>
        </dd>
      </dl>
      <button type="button" class="btn btn-secondary" data-testid="backup-refresh" :disabled="store.loading" @click="store.load()">Обновить статус</button>
    </template>
  </section>
</template>

<style scoped>
.backup-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field {
  font-size: 12.5px;
  color: var(--ink);
  margin-top: 8px;
}
.field-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.field-row input {
  width: 110px;
  flex: none;
}
.source {
  font-size: 12px;
  color: var(--ink-muted);
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.status {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 14px;
  margin: 18px 0 12px;
  font-size: 12.5px;
}
.status dt {
  color: var(--ink-muted);
}
.status dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
.failed {
  color: var(--status-crit);
}
</style>
