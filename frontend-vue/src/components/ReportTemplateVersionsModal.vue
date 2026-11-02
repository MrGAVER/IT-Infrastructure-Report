<script setup lang="ts">
// История версий шаблона отчёта: снимок сохраняется на каждое сохранение/восстановление (см.
// _snapshot_version в backend/app/api/report_builder.py) — сам config снимка наружу не
// отдаётся (см. ReportTemplateVersion в api/types.ts), просмотреть содержимое прошлой версии
// нельзя, только восстановить целиком. Текущее состояние тоже сохраняется как версия перед
// восстановлением — откат обратим.
import { onMounted, ref, useId } from 'vue'
import { listReportTemplateVersions, restoreReportTemplateVersion } from '../api/reportTemplates'
import type { ReportTemplate, ReportTemplateVersion } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { formatServerDateTime } from '../utils/dateTime'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore() // «Восстановить версию» меняет шаблон — только для роли с правом записи
const props = defineProps<{ template: ReportTemplate }>()
const emit = defineEmits<{ close: []; restored: [template: ReportTemplate] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const versions = ref<ReportTemplateVersion[]>([])
const loading = ref(true)
const restoringId = ref<string | null>(null)
const errorMessage = ref<string | null>(null)

onMounted(async () => {
  try {
    versions.value = await listReportTemplateVersions(props.template.id)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить историю версий'
  } finally {
    loading.value = false
  }
})

async function restore(v: ReportTemplateVersion) {
  if (!confirm(`Восстановить версию №${v.version_number} («${v.name}»)? Текущее состояние тоже сохранится в истории.`)) return
  errorMessage.value = null
  restoringId.value = v.id
  try {
    const restored = await restoreReportTemplateVersion(props.template.id, v.id)
    emit('restored', restored)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось восстановить версию'
  } finally {
    restoringId.value = null
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">История версий «{{ template.name }}»</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <p v-if="loading" class="loading-hint">Загрузка истории версий…</p>
      <p v-else-if="!versions.length" class="empty">Версий пока нет — они появляются при каждом сохранении изменений в существующем шаблоне.</p>
      <ul v-else class="version-list">
        <li v-for="v in versions" :key="v.id" class="version-row">
          <div class="version-info">
            <b>№{{ v.version_number }} — {{ v.name }}</b>
            <span class="version-meta"
              >{{ formatServerDateTime(v.created_at) }}<template v-if="v.description"> · {{ v.description }}</template></span
            >
          </div>
          <button v-if="auth.canWrite" type="button" class="btn btn-secondary" :disabled="restoringId === v.id" @click="restore(v)">
            {{ restoringId === v.id ? 'Восстановление…' : 'Восстановить' }}
          </button>
        </li>
      </ul>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" @click="$emit('close')">Закрыть</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 560px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 10px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
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
  margin-bottom: 14px;
}
.loading-hint,
.empty {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0;
}
.version-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
}
.version-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 11px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.version-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.version-info b {
  font-size: 12.5px;
}
.version-meta {
  font-size: 11px;
  color: var(--ink-muted);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
