<script setup lang="ts">
// Визуальный блочный редактор Word-шаблона (.docx) для шаблона конструктора отчётов. Портирован
// с блочного редактора vanilla-версии (до 2.60.0: rbRenderDocxEditor() и
// соседние rbXxx-функции) — тот же формат config.blocks (см.
// backend/app/services/report_engine.py:validate_config/report_render.py:build_docx). Блок
// "Таблица" — самостоятельный компонент DocxTableBlockEditor.vue (props-in/events-out, не
// мутирует состояние сам); остальные три типа блока (заголовок/абзац/разрыв страницы) достаточно
// простые, редактируются прямо здесь.
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getReportEntities } from '../api/reportEntities'
import { previewDocxConfig } from '../api/reportPreview'
import { getReportTemplate, saveReportTemplate } from '../api/reportTemplates'
import type { DocxBlock, DocxConfig, DocxPreviewResponse, ReportEntityMeta, ReportTemplate } from '../api/types'
import { useToast } from '../composables/useToast'
import DocxTableBlockEditor from '../components/DocxTableBlockEditor.vue'
import ScrollableTableWrap from '../components/ScrollableTableWrap.vue'

const route = useRoute()
const router = useRouter()
const { notify } = useToast()
const templateId = route.params.id as string

const loading = ref(true)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const template = ref<ReportTemplate | null>(null)
const entities = ref<ReportEntityMeta[]>([])

const name = ref('')
const description = ref('')
const blocks = ref<DocxBlock[]>([])

function newBlock(type: DocxBlock['type']): DocxBlock {
  if (type === 'heading') return { type: 'heading', text: '', level: 1 }
  if (type === 'paragraph') return { type: 'paragraph', text: '', align: 'left' }
  if (type === 'page_break') return { type: 'page_break' }
  return { type: 'table', title: '', root_entity: '', expand: '', include_empty_expand: true, sort_by: '', filters: [], columns: [] }
}

onMounted(async () => {
  try {
    const [t, e] = await Promise.all([getReportTemplate(templateId), getReportEntities()])
    template.value = t
    entities.value = e
    name.value = t.name
    description.value = t.description ?? ''
    const cfg = t.config as unknown as DocxConfig
    blocks.value = cfg.blocks && cfg.blocks.length ? cfg.blocks : [newBlock('heading')]
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить шаблон'
  } finally {
    loading.value = false
  }
})

function addBlock(type: DocxBlock['type']) {
  blocks.value.push(newBlock(type))
}
function removeBlock(i: number) {
  if (blocks.value.length <= 1) {
    notify('В шаблоне должен остаться хотя бы один блок.', 'error')
    return
  }
  if (!confirm('Удалить блок?')) return
  blocks.value.splice(i, 1)
}
function moveBlock(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= blocks.value.length) return
  const tmp = blocks.value[i]
  blocks.value[i] = blocks.value[j]
  blocks.value[j] = tmp
}
function updateBlock(i: number, patch: Partial<DocxBlock>) {
  Object.assign(blocks.value[i], patch)
}

const BLOCK_LABEL: Record<DocxBlock['type'], string> = {
  heading: 'Заголовок',
  paragraph: 'Абзац',
  page_break: 'Разрыв страницы',
  table: 'Таблица',
}

const paramHint = 'Текст (можно использовать {{параметр}} и {{report_date}})'

async function save() {
  errorMessage.value = null
  if (!name.value.trim()) {
    errorMessage.value = 'Укажите название шаблона.'
    return
  }
  saving.value = true
  try {
    const config: DocxConfig = { blocks: blocks.value }
    await saveReportTemplate(templateId, {
      name: name.value.trim(),
      description: description.value.trim() || null,
      format: 'docx',
      config: config as unknown as Record<string, unknown>,
    })
    notify('Шаблон сохранён', 'success')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить шаблон'
  } finally {
    saving.value = false
  }
}

function backToList() {
  router.push('/report-templates')
}

// ---------- Предпросмотр ----------
// Только для блоков-таблиц (см. block_tables()/preview_rows() в
// backend/app/services/report_render.py) — заголовок/абзац/разрыв страницы в предпросмотре не
// участвуют, показывать для них нечего.

const previewOpen = ref(false)
const previewLoading = ref(false)
const previewError = ref<string | null>(null)
const previewResult = ref<DocxPreviewResponse | null>(null)

async function runPreview() {
  previewOpen.value = true
  previewError.value = null
  previewLoading.value = true
  try {
    previewResult.value = await previewDocxConfig({ blocks: blocks.value } as unknown as Record<string, unknown>)
  } catch (err) {
    previewError.value = err instanceof Error ? err.message : 'Не удалось построить предпросмотр'
  } finally {
    previewLoading.value = false
  }
}
function closePreview() {
  previewOpen.value = false
}
function previewCellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}
</script>

<template>
  <div class="editor-view">
    <p v-if="loading" class="loading-hint">Загрузка шаблона…</p>

    <template v-else-if="errorMessage && !template">
      <div class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
    </template>

    <template v-else-if="template && template.format !== 'docx'">
      <p class="scope-note">
        Шаблон «{{ template.name }}» — в формате Excel (.xlsx). У него другой редактор — вернитесь к списку и откройте «Конструктор» ещё раз.
      </p>
      <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
    </template>

    <template v-else-if="template">
      <div class="top-bar">
        <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
        <label class="field">
          <span>Название</span>
          <input v-model.trim="name" type="text" />
        </label>
        <label class="field field-wide">
          <span>Описание</span>
          <input v-model.trim="description" type="text" />
        </label>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Сохранение…' : 'Сохранить' }}
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <div class="add-block-bar">
        <span>Добавить блок:</span>
        <button type="button" class="btn-mini" @click="addBlock('heading')">+ Заголовок</button>
        <button type="button" class="btn-mini" @click="addBlock('paragraph')">+ Абзац</button>
        <button type="button" class="btn-mini" @click="addBlock('table')">+ Таблица</button>
        <button type="button" class="btn-mini" @click="addBlock('page_break')">+ Разрыв страницы</button>
        <button type="button" class="btn-mini preview-trigger" @click="runPreview">Предпросмотр таблиц</button>
      </div>

      <div class="block-list">
        <div v-for="(b, i) in blocks" :key="i" class="block-card">
          <div class="block-head">
            <b>{{ BLOCK_LABEL[b.type] }}</b>
            <div class="block-actions">
              <button type="button" aria-label="Переместить блок вверх" :disabled="i === 0" @click="moveBlock(i, -1)">↑</button>
              <button type="button" aria-label="Переместить блок вниз" :disabled="i === blocks.length - 1" @click="moveBlock(i, 1)">↓</button>
              <button type="button" class="icon-btn danger" aria-label="Удалить блок" @click="removeBlock(i)">
                <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
              </button>
            </div>
          </div>

          <template v-if="b.type === 'heading'">
            <div class="row">
              <label class="field field-narrow">
                <span>Уровень</span>
                <select :value="b.level ?? 1" @change="updateBlock(i, { level: Number(($event.target as HTMLSelectElement).value) })">
                  <option v-for="lvl in [1, 2, 3, 4, 5, 6]" :key="lvl" :value="lvl">Заголовок {{ lvl }}</option>
                </select>
              </label>
              <label class="field field-wide">
                <span>{{ paramHint }}</span>
                <input type="text" :value="b.text" @input="updateBlock(i, { text: ($event.target as HTMLInputElement).value })" />
              </label>
            </div>
          </template>

          <template v-else-if="b.type === 'paragraph'">
            <div class="row">
              <label class="field field-narrow">
                <span>Выравнивание</span>
                <select :value="b.align ?? 'left'" @change="updateBlock(i, { align: ($event.target as HTMLSelectElement).value as 'left' | 'center' })">
                  <option value="left">По левому краю</option>
                  <option value="center">По центру</option>
                </select>
              </label>
              <label class="field field-wide">
                <span>Текст</span>
                <textarea :value="b.text" rows="2" @input="updateBlock(i, { text: ($event.target as HTMLTextAreaElement).value })"></textarea>
              </label>
            </div>
          </template>

          <DocxTableBlockEditor v-else-if="b.type === 'table'" :block="b" :entities="entities" @update="(patch) => updateBlock(i, patch)" />
        </div>
      </div>

      <div v-if="previewOpen" class="preview-panel">
        <div class="preview-panel-head">
          <b>Предпросмотр блоков-таблиц (первые записи)</b>
          <button type="button" class="icon-btn" aria-label="Закрыть предпросмотр" @click="closePreview">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
          </button>
        </div>
        <p v-if="previewLoading" class="loading-hint">Строим предпросмотр…</p>
        <p v-else-if="previewError" class="form-error">{{ previewError }}</p>
        <div v-else-if="previewResult" class="preview-sections">
          <p v-if="!previewResult.sections.length" class="loading-hint">В шаблоне нет блоков-таблиц для предпросмотра.</p>
          <div v-for="(section, si) in previewResult.sections" :key="si" class="preview-section">
            <div class="preview-section-head">
              <b>{{ section.title || `Таблица ${si + 1}` }}</b>
              <span v-if="section.total !== undefined" class="preview-note">показано записей: {{ section.total }}</span>
            </div>
            <p v-if="section.error" class="preview-error">{{ section.error }}</p>
            <ScrollableTableWrap v-else :label="`Предпросмотр: ${section.title || `Таблица ${si + 1}`}`">
              <table class="preview-table">
                <thead>
                  <tr>
                    <th v-for="(h, hi) in section.headers" :key="hi">{{ h }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in section.rows" :key="ri">
                    <td v-for="(value, ci) in row" :key="ci">{{ previewCellText(value) }}</td>
                  </tr>
                </tbody>
              </table>
            </ScrollableTableWrap>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.editor-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.loading-hint,
.scope-note {
  font-size: 12.5px;
  color: var(--ink-muted);
}
.scope-note {
  background: var(--surface-2);
  border-radius: var(--r-s);
  padding: 10px 12px;
}
.top-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field input,
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 9px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.field-wide {
  flex: 1;
  min-width: 200px;
}
.field-narrow {
  min-width: 150px;
}
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
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
.add-block-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.btn-mini {
  border: 1px dashed var(--border);
  background: none;
  border-radius: var(--r-s);
  padding: 6px 10px;
  font-size: 11.5px;
  color: var(--brand);
  cursor: pointer;
}
.block-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.block-card {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.block-head b {
  font-size: 12.5px;
}
.block-actions {
  display: flex;
  gap: 4px;
}
.block-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
  cursor: pointer;
}
.block-actions button:hover:not(:disabled) {
  color: var(--brand);
  background: var(--surface-2);
}
.block-actions button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.preview-trigger {
  margin-left: auto;
}
.preview-panel {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.preview-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.preview-panel-head b {
  font-size: 12.5px;
}
.preview-sections {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.preview-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.preview-section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.preview-section-head b {
  font-size: 12.5px;
}
.preview-note {
  font-size: 11px;
  color: var(--ink-muted);
}
.preview-error {
  font-size: 12px;
  color: var(--status-crit);
  margin: 0;
}
.preview-table {
  border-collapse: collapse;
}
.preview-table th,
.preview-table td {
  border: 1px solid var(--border);
  padding: 4px 8px;
  font-size: 11.5px;
  white-space: nowrap;
}
.preview-table th {
  background: var(--surface-2);
  text-align: left;
}
</style>
