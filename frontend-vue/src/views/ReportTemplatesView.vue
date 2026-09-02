<script setup lang="ts">
// Управление жизненным циклом шаблонов конструктора отчётов (список, создание, переименование,
// дублирование, удаление, генерация файла, история версий) — визуальный редактор содержимого
// открывается кнопкой "Конструктор" и ведёт на один из двух экранов в зависимости от формата:
// ReportGridEditorView.vue (xlsx) или ReportDocxEditorView.vue (docx), см. api/reportTemplates.ts.
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useReportTemplatesStore } from '../stores/reportTemplates'
import { deleteReportTemplate, duplicateReportTemplate, generateReportFromTemplate } from '../api/reportTemplates'
import { downloadReport } from '../api/reports'
import { useToast } from '../composables/useToast'
import type { ReportTemplate } from '../api/types'
import ReportTemplateFormModal from '../components/ReportTemplateFormModal.vue'
import ReportTemplateVersionsModal from '../components/ReportTemplateVersionsModal.vue'

const templates = useReportTemplatesStore()
const router = useRouter()
const { notify, notifyError } = useToast()

onMounted(async () => {
  await templates.ensureLoaded()
})

function openEditor(t: ReportTemplate) {
  router.push(t.format === 'xlsx' ? `/report-templates/${t.id}/editor` : `/report-templates/${t.id}/editor-docx`)
}

const modalTemplate = ref<ReportTemplate | null>(null)
const modalOpen = ref(false)
const versionsTemplate = ref<ReportTemplate | null>(null)
const busyId = ref<string | null>(null)

function openCreate() {
  modalTemplate.value = null
  modalOpen.value = true
}
function openEdit(t: ReportTemplate) {
  modalTemplate.value = t
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalTemplate.value = null
}
async function onSaved() {
  const wasEdit = modalTemplate.value !== null
  closeModal()
  await templates.reload()
  notify(wasEdit ? 'Шаблон обновлён' : 'Шаблон создан', 'success')
}

function openVersions(t: ReportTemplate) {
  versionsTemplate.value = t
}
function closeVersions() {
  versionsTemplate.value = null
}
async function onRestored() {
  closeVersions()
  await templates.reload()
  notify('Версия восстановлена', 'success')
}

async function removeTemplate(t: ReportTemplate) {
  if (!confirm(`Удалить шаблон «${t.name}»? Вместе с ним удалится вся история версий.`)) return
  busyId.value = t.id
  try {
    await deleteReportTemplate(t.id)
    await templates.reload()
    notify('Шаблон удалён', 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    busyId.value = null
  }
}

async function duplicate(t: ReportTemplate) {
  busyId.value = t.id
  try {
    await duplicateReportTemplate(t.id)
    await templates.reload()
    notify(`Создана копия «${t.name}»`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    busyId.value = null
  }
}

async function generate(t: ReportTemplate) {
  busyId.value = t.id
  try {
    const result = await generateReportFromTemplate(t.id)
    downloadReport(result)
    notify(`Отчёт сформирован: ${result.file_name}`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <div class="templates-view">
    <p class="scope-note">
      Список, создание, переименование, дублирование и история версий шаблонов — здесь.
      Визуальную раскладку листов и полей открывайте кнопкой «Открыть в конструкторе» —
      для xlsx-шаблонов это grid-редактор, для docx — блочный редактор.
    </p>

    <div class="filter-bar">
      <div class="search-box">
        <svg class="icon"><use href="/icons.svg#i-search" /></svg>
        <input v-model="templates.search" type="text" placeholder="Поиск по названию, описанию…" />
      </div>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="templates.loading" @click="templates.reload()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Новый шаблон
      </button>
    </div>

    <div class="table-card card">
      <div v-if="templates.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ templates.error }}
      </div>
      <div v-else-if="templates.loading && !templates.loaded" class="loading-banner">Загрузка шаблонов…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Название</th>
              <th>Формат</th>
              <th>Описание</th>
              <th>Обновлён</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in templates.filtered" :key="t.id">
              <td class="tname">{{ t.name }}</td>
              <td><span class="format-badge" :class="t.format">{{ t.format === 'xlsx' ? 'Excel' : 'Word' }}</span></td>
              <td class="desc-cell">{{ t.description || '—' }}</td>
              <td>{{ t.updated_at ? new Date(t.updated_at).toLocaleDateString('ru-RU') : '—' }}</td>
              <td>
                <div class="row-actions">
                  <button
                    type="button"
                    aria-label="Открыть в конструкторе"
                    title="Открыть в конструкторе"
                    @click="openEditor(t)"
                  >
                    <svg class="icon"><use href="/icons.svg#i-grid" /></svg>
                  </button>
                  <button type="button" aria-label="Сформировать" :disabled="busyId === t.id" @click="generate(t)">
                    <svg class="icon"><use href="/icons.svg#i-download" /></svg>
                  </button>
                  <button type="button" aria-label="Дублировать" :disabled="busyId === t.id" @click="duplicate(t)">
                    <svg class="icon"><use href="/icons.svg#i-layers" /></svg>
                  </button>
                  <button type="button" aria-label="История версий" @click="openVersions(t)">
                    <svg class="icon"><use href="/icons.svg#i-activity" /></svg>
                  </button>
                  <button type="button" aria-label="Переименовать" @click="openEdit(t)">
                    <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
                  </button>
                  <button type="button" aria-label="Удалить" :disabled="busyId === t.id" @click="removeTemplate(t)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!templates.filtered.length">
              <td colspan="5" class="empty-row">Шаблоны не найдены.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <ReportTemplateFormModal v-if="modalOpen" :template="modalTemplate" @close="closeModal" @saved="onSaved" />
    <ReportTemplateVersionsModal v-if="versionsTemplate" :template="versionsTemplate" @close="closeVersions" @restored="onRestored" />
  </div>
</template>

<style scoped>
.templates-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.scope-note {
  font-size: 11.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border-radius: var(--r-s);
  padding: 9px 12px;
  margin: 0;
}
.scope-note code {
  font-family: var(--font-mono);
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 7px 10px;
  min-width: 260px;
  max-width: 420px;
}
.search-box .icon {
  color: var(--ink-muted);
}
.search-box input {
  border: none;
  background: transparent;
  outline: none;
  color: var(--ink);
  font-size: 12.5px;
  width: 100%;
}
.spacer {
  flex: 1;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}
thead th {
  text-align: left;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  font-weight: 600;
  white-space: nowrap;
}
tbody td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: top;
}
tbody tr:last-child td {
  border-bottom: none;
}
.tname {
  font-weight: 600;
}
.desc-cell {
  color: var(--ink-muted);
  max-width: 320px;
}
.format-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
}
.format-badge.xlsx {
  background: rgba(45, 212, 158, 0.14);
  color: #2dd49e;
}
.format-badge.docx {
  background: rgba(96, 165, 250, 0.14);
  color: #60a5fa;
}
.row-actions {
  display: flex;
  gap: 4px;
}
.row-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
  cursor: pointer;
}
.row-actions button:hover:not(:disabled) {
  color: var(--brand);
  background: var(--surface-2);
}
.row-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.row-actions .icon {
  width: 15px;
  height: 15px;
}
.error-banner,
.loading-banner {
  padding: 14px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.error-banner {
  color: var(--status-crit);
}
.empty-row {
  text-align: center;
  color: var(--ink-muted);
  padding: 24px;
}
</style>
