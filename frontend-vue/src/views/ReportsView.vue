<script setup lang="ts">
// Регламентный отчёт (Листы 1-4) — ключевая функция приложения (см. Общее описание
// приложения). Здесь только вызов уже существующей серверной генерации с фильтрами;
// визуальный конструктор произвольных отчётов (report_builder.py, drag-and-drop
// grid-редактор) не переносится на новый стек в этой итерации — слишком большая
// отдельная задача, см. README.
import { onMounted, ref } from 'vue'
import { useInformationSystemsStore } from '../stores/informationSystems'
import { useCatalogsStore } from '../stores/catalogs'
import { generateInventoryReport, generateAuditLogReport, downloadReport } from '../api/reports'
import { useToast } from '../composables/useToast'
import StructuralUnitTree from '../components/StructuralUnitTree.vue'

const systems = useInformationSystemsStore()
const catalogs = useCatalogsStore()
const { notify, notifyError } = useToast()

onMounted(async () => {
  await Promise.all([systems.ensureLoaded(), catalogs.ensureLoaded()])
})

const selectedIS = ref('')
const selectedUnitIds = ref<string[]>([])
const inventoryLoading = ref(false)

function toggleUnit(id: string) {
  const idx = selectedUnitIds.value.indexOf(id)
  if (idx === -1) selectedUnitIds.value.push(id)
  else selectedUnitIds.value.splice(idx, 1)
}

async function runInventoryReport() {
  inventoryLoading.value = true
  try {
    const result = await generateInventoryReport(selectedIS.value || null, selectedUnitIds.value)
    downloadReport(result)
    notify(`Отчёт сформирован: ${result.file_name}`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    inventoryLoading.value = false
  }
}

const dateFrom = ref('')
const dateTo = ref('')
const auditLoading = ref(false)

async function runAuditLogReport() {
  auditLoading.value = true
  try {
    const result = await generateAuditLogReport(dateFrom.value || null, dateTo.value || null)
    downloadReport(result)
    notify(`Выгрузка журнала аудита сформирована: ${result.file_name}`, 'success')
  } catch (err) {
    notifyError(err)
  } finally {
    auditLoading.value = false
  }
}
</script>

<template>
  <div class="reports-view">
    <section class="card report-card">
      <div class="report-head">
        <h2>Регламентный отчёт</h2>
        <p>Excel, 4 листа: информационные системы, инвентаризация устройств, подключения, виртуальные машины.</p>
      </div>

      <div class="filters">
        <label class="field">
          <span>Ограничить одной информационной системой</span>
          <select v-model="selectedIS">
            <option value="">— все ИС —</option>
            <option v-for="s in systems.all" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </label>

        <details class="tree-pop">
          <summary class="fbtn">
            <svg class="icon"><use href="/icons.svg#i-sitemap" /></svg>
            Ограничить структурными единицами
            <span v-if="selectedUnitIds.length" class="count-badge">{{ selectedUnitIds.length }}</span>
            <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
          </summary>
          <div class="tree-panel">
            <p v-if="!catalogs.structuralUnitTree.length" class="empty-hint">Структурные единицы ещё не заведены в справочнике.</p>
            <StructuralUnitTree v-else :nodes="catalogs.structuralUnitTree" :selected="selectedUnitIds" @toggle="toggleUnit" />
          </div>
        </details>
      </div>

      <p class="scope-note">Без фильтров отчёт включает весь реестр — как при нажатии «Сформировать» без ограничений в текущем интерфейсе.</p>

      <button class="btn btn-primary" :disabled="inventoryLoading" @click="runInventoryReport">
        <svg class="icon"><use href="/icons.svg#i-download" /></svg>
        {{ inventoryLoading ? 'Формирование…' : 'Сформировать и скачать' }}
      </button>
    </section>

    <section class="card report-card">
      <div class="report-head">
        <h2>Журнал аудита</h2>
        <p>Excel-выгрузка изменений реестра за период.</p>
      </div>

      <div class="filters">
        <label class="field">
          <span>С даты</span>
          <input v-model="dateFrom" type="date" />
        </label>
        <label class="field">
          <span>По дату</span>
          <input v-model="dateTo" type="date" />
        </label>
      </div>

      <button class="btn btn-primary" :disabled="auditLoading" @click="runAuditLogReport">
        <svg class="icon"><use href="/icons.svg#i-download" /></svg>
        {{ auditLoading ? 'Формирование…' : 'Сформировать и скачать' }}
      </button>
    </section>

    <p class="builder-note">
      Визуальный конструктор произвольных отчётов и Word-шаблонов пока доступен только в
      текущем vanilla-интерфейсе.
    </p>
  </div>
</template>

<style scoped>
.reports-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 620px;
}
.report-card {
  padding: 20px 22px;
}
.report-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0 0 4px;
}
.report-head p {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0 0 16px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-bottom: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
  flex: 1;
  min-width: 200px;
}
.field select,
.field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.fbtn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 8px 11px;
  font-size: 12px;
  color: var(--ink);
  font-weight: 500;
  cursor: pointer;
  list-style: none;
  height: 38px;
}
.fbtn::-webkit-details-marker {
  display: none;
}
.count-badge {
  background: var(--brand);
  color: #05161c;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
}
.tree-pop {
  position: relative;
}
.tree-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 20;
  width: 280px;
  max-height: 300px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px 12px;
  box-shadow: 0 12px 28px -10px rgba(0, 0, 0, 0.5);
}
.empty-hint {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0;
}
.scope-note {
  font-size: 11px;
  color: var(--ink-muted);
  margin: 0 0 14px;
}
.builder-note {
  font-size: 11.5px;
  color: var(--ink-muted);
  text-align: center;
  margin-top: 4px;
}
</style>
