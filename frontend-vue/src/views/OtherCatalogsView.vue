<script setup lang="ts">
// OtherCatalogsView.vue (п.6) — единый экран для добавления/редактирования/удаления записей
// справочников, у которых нет отдельного экрана управления: раньше их можно было только
// "быстро добавить" через "+" в других формах (QuickAddModal.vue), без возможности посмотреть
// список целиком, отредактировать или удалить запись.
//
// OTHER_CATALOGS сознательно НЕ включает: buildings/rooms/racks (свой экран —
// BuildingsView.vue), structural-units (свой экран), vlans/vlan-domains (управляются на
// VLANsView.vue, включая панель "Домены VLAN") — добавлять их сюда означало бы дублировать уже
// существующий, более удобный для этих сущностей UI (у зданий — вложенность
// здание/помещение/стойка, у VLAN — таблица с фильтрами).
import { computed, onMounted, ref, watch } from 'vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { QUICK_ADD_FIELDS, QUICK_ADD_LABELS } from '../quickAdd/schema'
import type { QuickField } from '../quickAdd/schema'
import { useToast } from '../composables/useToast'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import CatalogRecordFormModal from '../components/CatalogRecordFormModal.vue'

const OTHER_CATALOGS = [
  'device-types',
  'manufacturers',
  'device-models',
  'os-categories',
  'operating-systems',
  'embedded-os',
  'interface-types',
  'interface-speeds',
  'connection-types',
  'protocol-port-catalog',
  'support-organizations',
  'support-methods',
  'crypto-protection-means',
  'software-assets',
  'departments',
  'placement-assets',
] as const
type OtherCatalogKey = (typeof OTHER_CATALOGS)[number]

// catalog — ключ справочника, который нужно открыть (маршрут передаёт его из ?catalog=, см. router/index.ts;
// так дашборд ведёт на «Программные активы»). Неизвестное значение игнорируется: открывается первый справочник.
const props = defineProps<{ catalog?: string }>()

function isOtherCatalogKey(value: string | undefined): value is OtherCatalogKey {
  return OTHER_CATALOGS.some((key) => key === value)
}

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const { notify, notifyError } = useToast()
const loading = ref(true)

onMounted(async () => {
  try {
    // devicesStore — нужен для отображения/выбора "Физическое устройство" у
    // crypto-protection-means (QuickField.fkSource==='devices', см. quickAdd/schema.ts);
    // остальные 15 справочников этого экрана его не используют, но раздельная загрузка ради
    // одного поля не оправдана — тот же компромисс, что и во всех остальных ensureLoaded() в
    // этом приложении (см. комментарий в stores/devices.ts).
    await Promise.all([catalogs.ensureLoaded(), devicesStore.ensureLoaded()])
  } catch (err) {
    notifyError(err)
  } finally {
    loading.value = false
  }
})

const selected = ref<OtherCatalogKey>(isOtherCatalogKey(props.catalog) ? props.catalog : 'device-types')
// Тот же компонент остаётся на экране, когда меняется только ?catalog= (переход по ссылке, «назад»/«вперёд»).
watch(
  () => props.catalog,
  (key) => {
    if (isOtherCatalogKey(key)) selected.value = key
  },
)
const fields = computed<QuickField[]>(() => QUICK_ADD_FIELDS[selected.value] ?? [])

/** protocol-port-catalog хранится отдельно от остальных каталогов (у записей нет поля name —
 * см. комментарий к ProtocolPortCatalogEntry в stores/catalogs.ts), остальные 16 — в общем
 * catalogs.items. */
const records = computed<Record<string, unknown>[]>(() => {
  if (selected.value === 'protocol-port-catalog') return catalogs.protocolPortCatalog as unknown as Record<string, unknown>[]
  return (catalogs.items[selected.value as keyof typeof catalogs.items] ?? []) as unknown as Record<string, unknown>[]
})

function recordCount(key: OtherCatalogKey): number {
  if (key === 'protocol-port-catalog') return catalogs.protocolPortCatalog.length
  return (catalogs.items[key as keyof typeof catalogs.items] ?? []).length
}

function cellValue(record: Record<string, unknown>, field: QuickField): string {
  const raw = record[field.name]
  if (field.type === 'fk' && field.fkResource) {
    if (field.fkSource === 'devices') {
      const device = devicesStore.all.find((d) => d.id === raw)
      return device ? device.system_name || device.serial_number : '—'
    }
    return catalogs.label(field.fkResource as keyof typeof catalogs.items, raw as string | null | undefined)
  }
  if (field.type === 'checkbox') return raw ? 'Да' : 'Нет'
  if (raw === null || raw === undefined || raw === '') return '—'
  return String(raw)
}

const modalOpen = ref(false)
const editingItem = ref<Record<string, unknown> | null>(null)

function openCreate() {
  editingItem.value = null
  modalOpen.value = true
}
function openEdit(record: Record<string, unknown>) {
  editingItem.value = record
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  editingItem.value = null
}
async function onSaved() {
  const wasEdit = editingItem.value !== null
  closeModal()
  await catalogs.reload()
  notify(wasEdit ? 'Запись обновлена' : 'Запись добавлена', 'success')
}
async function onDeleted() {
  closeModal()
  await catalogs.reload()
  notify('Запись удалена', 'success')
}
</script>

<template>
  <div class="other-catalogs">
    <header class="page-head">
      <div>
        <h1>Другие справочники</h1>
        <p class="hint">
          Значения, которые раньше можно было только быстро добавить через «+» в других формах — здесь их можно посмотреть списком,
          отредактировать или удалить.
        </p>
      </div>
    </header>

    <div v-if="loading" class="empty-state">Загрузка…</div>
    <div v-else class="layout">
      <nav class="catalog-list" aria-label="Список справочников">
        <button
          v-for="key in OTHER_CATALOGS"
          :key="key"
          type="button"
          class="catalog-item"
          :class="{ active: key === selected }"
          @click="selected = key"
        >
          <span v-truncate-tooltip>{{ QUICK_ADD_LABELS[key] ?? key }}</span>
          <span class="count">{{ recordCount(key) }}</span>
        </button>
      </nav>

      <section class="catalog-content">
        <div class="content-head">
          <h2>{{ QUICK_ADD_LABELS[selected] ?? selected }}</h2>
          <button type="button" class="btn btn-primary" :disabled="!fields.length" @click="openCreate">
            <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
            Добавить
          </button>
        </div>

        <p v-if="!fields.length" class="empty-state">Для «{{ selected }}» форма редактирования не настроена.</p>
        <p v-else-if="!records.length" class="empty-state">Записей пока нет.</p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th v-for="f in fields" :key="f.name">{{ f.label }}</th>
                <th class="col-actions"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="record in records" :key="String(record.id)">
                <td v-for="f in fields" :key="f.name">
                  <span class="cell-text" v-truncate-tooltip>{{ cellValue(record, f) }}</span>
                </td>
                <td class="col-actions">
                  <button type="button" class="icon-btn" aria-label="Редактировать" @click="openEdit(record)">
                    <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <CatalogRecordFormModal
      v-if="modalOpen"
      :resource="selected"
      :item="editingItem"
      @close="closeModal"
      @saved="onSaved"
      @deleted="onDeleted"
    />
  </div>
</template>

<style scoped>
.other-catalogs {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.page-head h1 {
  font-family: var(--font-display);
  font-size: 20px;
  margin: 0 0 4px;
}
.hint {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0;
  max-width: 640px;
}
.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
}
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  align-items: start;
}
.catalog-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 6px;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}
.catalog-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  border: none;
  border-radius: var(--r-s);
  background: transparent;
  color: var(--ink-muted);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
}
.catalog-item span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.catalog-item:hover {
  background: var(--surface-2);
  color: var(--ink);
}
.catalog-item.active {
  background: var(--surface-2);
  color: var(--ink);
  font-weight: 600;
}
.catalog-item .count {
  flex-shrink: 0;
  min-width: 20px;
  text-align: center;
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-3, var(--surface));
  color: var(--ink-muted);
}

.catalog-content {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 16px;
  min-width: 0;
}
.content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.content-head h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.content-head .btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
thead th {
  text-align: left;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: middle;
  max-width: 260px;
}
tbody tr:last-child td {
  border-bottom: none;
}
.cell-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-actions {
  width: 1%;
  text-align: right;
}

@media (max-width: 860px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .catalog-list {
    flex-direction: row;
    flex-wrap: wrap;
    max-height: none;
  }
  .catalog-item {
    width: auto;
  }
}
</style>
