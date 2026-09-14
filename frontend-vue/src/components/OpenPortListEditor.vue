<script setup lang="ts">
// Редактор вложенного списка открытых портов/протоколов (OpenPort — полиморфная
// таблица, см. api/types.ts). Сознательно не знает про owner_type/owner_id и не
// обращается к API сам — те же причины, что в VmIpListEditor.vue. Благодаря этому
// один и тот же компонент уже сегодня закрывает ВМ (VMFormModal.vue) и без
// изменений годится для физических устройств, когда до них дойдёт очередь (см.
// "Ещё не сделано" в frontend-vue/README.md: "привязка ... открытых портов к
// устройству" — в vanilla-фронтенде это saveDeviceOpenPorts в vm-editors.js,
// почти дословно совпадающий с saveVMOpenPorts).
import type { OpenPortDraftRow, ProtocolPortCatalogEntry, CatalogItem } from '../api/types'
import QuickAddButton from './QuickAddButton.vue'

const props = defineProps<{ modelValue: OpenPortDraftRow[]; catalogEntries: ProtocolPortCatalogEntry[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: OpenPortDraftRow[]] }>()

// Фикс п.1.5/4.3 ("дублирование полей 'Протокол' и блок с выбором TCP/UDP"): поля НЕ объединены,
// т.к. это разные атрибуты одной и той же записи открытого порта, оба нужны для отчёта Excel
// (backend/app/reporting.py собирает ячейку как "{transport_protocol}/{port}, {protocol}, ...") —
// protocol здесь прикладной уровень (SSH, HTTPS), transport_protocol — транспортный (TCP/UDP).
// Реальная причина путаницы — оба поля были без подписи (голый placeholder на входе, у select
// вообще никакой), из-за чего "TCP" в select рядом с "SSH"/"TCP/HTTPS" в текстовом поле читались
// как одно и то же. Правка — только title/placeholder, без изменения модели данных.
const TRANSPORT_OPTIONS = ['TCP', 'UDP', 'TCP/UDP']

function emptyRow(): OpenPortDraftRow {
  return { protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }
}

function catalogLabel(entry: ProtocolPortCatalogEntry): string {
  return `${entry.port} / ${entry.protocol_type}`
}

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateField(index: number, patch: Partial<OpenPortDraftRow>) {
  const next = props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}

// Выбор записи справочника подставляет порт и протокол — как onVMOpenPortCatalogChanged()
// в vanilla-версии (frontend/static/vm-editors.js). Пользователь может отредактировать
// оба поля вручную после — справочник только ускоряет типичный случай.
function onCatalogChange(index: number, catalogId: string) {
  const entry = props.catalogEntries.find((e) => e.id === catalogId)
  updateField(index, {
    protocol_catalog_id: catalogId,
    ...(entry ? { port: String(entry.port), protocol: entry.protocol_type } : {}),
  })
}

// Быстро добавленная запись используется НАПРЯМУЮ (не через onCatalogChange, который ищет
// её в props.catalogEntries) — на момент этого вызова прокинутый вниз проп catalogEntries ещё
// не обязательно успел обновиться: обновление стора в QuickAddModal.vue и эмит 'created'
// происходят синхронно, до следующего цикла реактивности/рендера родителя, так что при поиске
// по props.catalogEntries новая запись иногда ещё не была бы найдена. У record уже есть все
// нужные поля — используем их напрямую, без обхода через поиск.
function onQuickAdded(index: number, record: CatalogItem) {
  const entry = record as unknown as ProtocolPortCatalogEntry
  updateField(index, { protocol_catalog_id: entry.id, port: String(entry.port), protocol: entry.protocol_type })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Открытые порты / протоколы</b>
      <span class="hint">Используются при заполнении соответствующего поля отчёта.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">Открытые порты не добавлены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <div class="col-catalog lookup-row">
        <select
          :value="row.protocol_catalog_id"
          @change="onCatalogChange(i, ($event.target as HTMLSelectElement).value)"
        >
          <option value="">— справочник —</option>
          <option v-for="entry in catalogEntries" :key="entry.id" :value="entry.id">{{ catalogLabel(entry) }}</option>
        </select>
        <QuickAddButton resource="protocol-port-catalog" title="Протокол / порт" @created="(r) => onQuickAdded(i, r)" />
      </div>
      <input
        class="col-port"
        type="number"
        min="1"
        max="65535"
        placeholder="Порт"
        :value="row.port"
        @input="updateField(i, { port: ($event.target as HTMLInputElement).value })"
      />
      <input
        class="col-protocol"
        type="text"
        placeholder="Протокол (напр. SSH)"
        title="Протокол — прикладного уровня (SSH, HTTPS, SNMP и т.п.), не путать с транспортным протоколом справа"
        :value="row.protocol"
        @input="updateField(i, { protocol: ($event.target as HTMLInputElement).value })"
      />
      <select
        class="col-transport"
        title="Транспортный протокол (TCP/UDP) — отдельно от прикладного протокола слева"
        :value="row.transport_protocol"
        @change="updateField(i, { transport_protocol: ($event.target as HTMLSelectElement).value })"
      >
        <option v-for="t in TRANSPORT_OPTIONS" :key="t" :value="t">{{ t }}</option>
      </select>
      <input
        class="col-desc"
        type="text"
        placeholder="Описание"
        :value="row.description"
        @input="updateField(i, { description: ($event.target as HTMLInputElement).value })"
      />
      <button type="button" class="icon-btn danger" aria-label="Удалить открытый порт" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      Открытый порт
    </button>
  </div>
</template>

<style scoped>
.nested-editor {
  grid-column: 1 / -1;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.nested-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 2px;
}
.nested-head b {
  font-size: 12.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.nested-row {
  display: grid;
  grid-template-columns: 1.5fr 0.7fr 1fr 0.9fr 1.3fr auto;
  align-items: center;
  gap: 8px;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lookup-row select {
  flex: 1;
  min-width: 0;
}
.nested-row input,
.nested-row select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  width: 100%;
  font-family: inherit;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
.add-btn {
  align-self: flex-start;
}

@media (max-width: 720px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
}
</style>
