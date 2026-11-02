<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Device, DeviceStack } from '../api/types'
import PageSizeSelect from '../components/PageSizeSelect.vue'
import StatCard from '../components/StatCard.vue'
import StructuralUnitTree from '../components/StructuralUnitTree.vue'
import DeviceFormModal from '../components/DeviceFormModal.vue'
import DeviceTableRow from '../components/DeviceTableRow.vue'
import DeviceStackFormModal from '../components/DeviceStackFormModal.vue'
// Общая панель фильтров (поиск, селекты, кнопки действий) — UI-10/UI-11.
import '../styles/list-toolbar.css'

const devices = useDevicesStore()
const catalogs = useCatalogsStore()
const vlans = useVLANsStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const modalDevice = ref<Device | null>(null)
// Фикс п.2: "копировать физическое устройство для создания на его основе нового" — модалка
// открывается в режиме СОЗДАНИЯ (modalDevice остаётся null), но с данными исходного устройства
// в качестве шаблона (см. подробности в DeviceFormModal.vue: watch(copySourceId, ...)).
const copyFromDevice = ref<Device | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

// Пункты 1-2 правки "инвентаризация физических устройств": создание стека и раскрытие его
// строки в этой же таблице (см. stores/devices.ts:groupedFiltered).
const stackModalOpen = ref(false)
const stackModalStack = ref<DeviceStack | null>(null)
const expandedStacks = ref(new Set<string>())

onMounted(async () => {
  // vlans — не для собственной таблицы этого экрана, а для выпадающего списка VLAN в
  // DeviceVlanListEditor.vue внутри DeviceFormModal.vue (тот же приём, что в
  // InformationSystemsView.vue: форма читает уже загруженный стор, а не грузит сама).
  await Promise.all([devices.ensureLoaded(), catalogs.ensureLoaded(), vlans.ensureLoaded()])
})

watch(
  () => [devices.search, devices.buildingId, devices.deviceTypeId, devices.siemFilter, devices.structuralUnitIds],
  () => devices.resetPageOnFilterChange(),
  { deep: true },
)

function toggleUnit(id: string) {
  const idx = devices.structuralUnitIds.indexOf(id)
  if (idx === -1) devices.structuralUnitIds.push(id)
  else devices.structuralUnitIds.splice(idx, 1)
}

function toggleStack(id: string) {
  if (expandedStacks.value.has(id)) expandedStacks.value.delete(id)
  else expandedStacks.value.add(id)
}

/** Русское склонение "N устройство/устройства/устройств" для счётчика в строке стека. */
function deviceCountLabel(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  const word = mod10 === 1 && mod100 !== 11 ? 'устройство' : mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14) ? 'устройства' : 'устройств'
  return `${n} ${word}`
}

const siemCount = () => devices.all.filter((d) => d.siem_enabled).length
const serverTypeName = 'Сервер'

function openCreate() {
  modalDevice.value = null
  copyFromDevice.value = null
  modalOpen.value = true
}
function openEdit(d: Device) {
  modalDevice.value = d
  copyFromDevice.value = null
  modalOpen.value = true
}
function openCopy(d: Device) {
  modalDevice.value = null
  copyFromDevice.value = d
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalDevice.value = null
  copyFromDevice.value = null
}
async function onSaved(_saved: Device) {
  const wasEdit = modalDevice.value !== null
  closeModal()
  await devices.reload()
  notify(wasEdit ? 'Устройство обновлено' : 'Устройство добавлено', 'success')
}

async function removeDevice(d: Device) {
  const label = d.system_name || d.serial_number
  if (!confirm(`Удалить устройство «${label}»?`)) return
  deletingId.value = d.id
  try {
    await deleteResource('devices', d.id)
    await devices.reload()
    notify('Устройство удалено', 'success')
  } catch (err) {
    // REFERENCED_BY_OTHER_RECORDS и любые другие ошибки удаления одинаково
    // приходят с читаемым message с бэкенда (см. delete_resource) — достаточно
    // показать как есть, без ветвления по коду.
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}

function openCreateStack() {
  stackModalStack.value = null
  stackModalOpen.value = true
}
function closeStackModal() {
  stackModalOpen.value = false
  stackModalStack.value = null
  // Добавление/удаление участников стека (внутри DeviceStackFormModal.vue) применяется сразу
  // по клику, а не только по кнопке "Сохранить" формы — перезагружаем реестр устройств при
  // ЛЮБОМ закрытии модалки (а не только в onStackSaved ниже), иначе принадлежность к стеку и
  // номер позиции в этой таблице могли бы остаться устаревшими, закрой пользователь её крестиком.
  devices.reload()
}
async function onStackSaved(stack: DeviceStack) {
  const wasCreate = stackModalStack.value === null
  await devices.reload()
  if (wasCreate) {
    // Стек только что создан и пока пуст — сразу переключаем ЭТУ ЖЕ модалку в режим
    // редактирования (watch(() => props.stack, ...) в DeviceStackFormModal.vue отработает сам
    // от смены пропса), чтобы добавить участников можно было тут же, не открывая форму заново и
    // не уходя на отдельный экран "Стеки устройств".
    stackModalStack.value = stack
    notify('Стек создан — добавьте устройства ниже', 'success')
  } else {
    stackModalOpen.value = false
    stackModalStack.value = null
    notify('Стек обновлён', 'success')
  }
}
</script>

<template>
  <div class="devices-view">
    <div class="stat-row">
      <StatCard :value="devices.total" label="Всего устройств" />
      <StatCard :value="devices.all.filter((d) => catalogs.label('device-types', d.device_type_id) === serverTypeName).length" label="Серверы" />
      <StatCard :value="siemCount()" label="С покрытием SIEM" />
      <StatCard :value="devices.total - siemCount()" label="Без покрытия SIEM" tone="warn" />
    </div>

    <div class="filter-bar list-toolbar">
      <div class="filter-fields">
        <div class="search-box">
          <svg class="icon"><use href="/icons.svg#i-search" /></svg>
          <input
            v-model="devices.search"
            type="text"
            placeholder="Поиск по имени, серийному №, IP…"
            title="Поиск по имени, серийному номеру, IP-адресу и описанию"
            aria-label="Поиск по имени, серийному номеру, IP-адресу и описанию"
          />
        </div>

        <select v-model="devices.buildingId" class="fbtn" aria-label="Здание">
          <option value="">Здание: все</option>
          <option v-for="b in catalogs.items['buildings'] ?? []" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>

        <select v-model="devices.deviceTypeId" class="fbtn" aria-label="Тип устройства">
          <option value="">Тип устройства: все</option>
          <option v-for="t in catalogs.items['device-types'] ?? []" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>

        <div class="chip-group">
          <button :class="{ on: devices.siemFilter === 'all' }" @click="devices.siemFilter = 'all'">SIEM: все</button>
          <button :class="{ on: devices.siemFilter === 'yes' }" @click="devices.siemFilter = 'yes'">Да</button>
          <button :class="{ on: devices.siemFilter === 'no' }" @click="devices.siemFilter = 'no'">Нет</button>
        </div>

        <details class="tree-pop">
          <summary class="fbtn">
            <svg class="icon"><use href="/icons.svg#i-sitemap" /></svg>
            Структурные подразделения
            <span v-if="devices.structuralUnitIds.length" class="count-badge">{{ devices.structuralUnitIds.length }}</span>
            <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
          </summary>
          <div class="tree-panel">
            <p v-if="!catalogs.structuralUnitTree.length" class="empty-hint">Структурные единицы ещё не заведены в справочнике.</p>
            <StructuralUnitTree v-else :nodes="catalogs.structuralUnitTree" :selected="devices.structuralUnitIds" @toggle="toggleUnit" />
          </div>
        </details>
      </div>

      <div class="filter-actions">
        <button class="btn btn-secondary" :disabled="devices.loading" @click="devices.reload()">
          <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
          Обновить
        </button>
        <button v-if="auth.canWrite" class="btn btn-secondary" @click="openCreateStack">
          <svg class="icon"><use href="/icons.svg#i-layers" /></svg>
          Стек
        </button>
        <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreate">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Добавить устройство
        </button>
      </div>
    </div>

    <div class="table-card card">
      <div v-if="devices.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ devices.error }}
      </div>
      <div v-else-if="devices.loading && !devices.loaded" class="loading-banner">Загрузка реестра устройств…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Тип</th>
              <th>Системное имя</th>
              <th>Серийный №</th>
              <th>Производитель / модель</th>
              <th>ОС</th>
              <th>IP управления</th>
              <th>Здание · помещение</th>
              <th>SIEM</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in devices.pageItems" :key="row.kind === 'device' ? row.device.id : 'stack-' + row.stackId">
              <DeviceTableRow
                v-if="row.kind === 'device'"
                :device="row.device"
                :removing="deletingId === row.device.id"
                :read-only="!auth.canWrite"
                @edit="openEdit"
                @copy="openCopy"
                @remove="removeDevice"
              />
              <template v-else>
                <tr class="stack-summary-row">
                  <td colspan="9">
                    <button type="button" class="stack-toggle" :aria-expanded="expandedStacks.has(row.stackId)" @click="toggleStack(row.stackId)">
                      <svg class="icon chev" :class="{ open: expandedStacks.has(row.stackId) }"><use href="/icons.svg#i-chevd" /></svg>
                      <svg class="icon stack-icon"><use href="/icons.svg#i-layers" /></svg>
                      <b>{{ row.stackName }}</b>
                      <span class="stack-count">{{ deviceCountLabel(row.members.length) }}</span>
                    </button>
                  </td>
                </tr>
                <template v-if="expandedStacks.has(row.stackId)">
                  <DeviceTableRow
                    v-for="m in row.members"
                    :key="m.id"
                    :device="m"
                    :stack-position="m.stack_position"
                    :removing="deletingId === m.id"
                    :read-only="!auth.canWrite"
                    @edit="openEdit"
                    @copy="openCopy"
                    @remove="removeDevice"
                  />
                </template>
              </template>
            </template>
            <tr v-if="!devices.filtered.length">
              <td colspan="9" class="empty-row">Ничего не найдено по заданным фильтрам.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-foot">
        <span
          >Показано {{ devices.pageItems.length ? (devices.page - 1) * devices.pageSize + 1 : 0 }}–{{
            (devices.page - 1) * devices.pageSize + devices.pageItems.length
          }}
          из {{ devices.groupedFiltered.length }}</span
        >
        <PageSizeSelect :model-value="devices.pageSize" :options="devices.pageSizeOptions" @update:model-value="devices.setPageSize" />
        <div class="pager">
          <button :disabled="devices.page <= 1" @click="devices.setPage(devices.page - 1)">‹</button>
          <button v-for="p in devices.pageCount" :key="p" :class="{ on: p === devices.page }" @click="devices.setPage(p)">{{ p }}</button>
          <button :disabled="devices.page >= devices.pageCount" @click="devices.setPage(devices.page + 1)">›</button>
        </div>
      </div>
    </div>

    <DeviceFormModal v-if="modalOpen" :device="modalDevice" :copy-from="copyFromDevice" @close="closeModal" @saved="onSaved" />
    <DeviceStackFormModal v-if="stackModalOpen" :stack="stackModalStack" @close="closeStackModal" @saved="onStackSaved" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.tree-pop {
  position: relative;
}
.tree-pop > summary {
  list-style: none;
  cursor: pointer;
}
.tree-pop > summary::-webkit-details-marker {
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
.tree-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 20;
  width: 280px;
  max-height: 320px;
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
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 880px;
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
  vertical-align: middle;
}
tbody tr:last-child td {
  border-bottom: none;
}
tbody tr:hover td {
  background: var(--surface-2);
}
.stack-summary-row td {
  padding: 0;
}
.stack-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  padding: 10px 14px;
  cursor: pointer;
  text-align: left;
  color: var(--ink);
  font-size: 12.5px;
  font-family: inherit;
}
.stack-toggle b {
  font-weight: 600;
}
.stack-toggle .stack-icon {
  color: var(--brand);
}
.stack-toggle .chev {
  transition: transform 0.15s ease;
  color: var(--ink-muted);
}
.stack-toggle .chev.open {
  transform: rotate(180deg);
}
.stack-count {
  color: var(--ink-muted);
  font-size: 11px;
  margin-left: auto;
}
.empty-row {
  text-align: center;
  color: var(--ink-muted);
  padding: 26px 14px;
}
.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px;
  color: var(--status-crit);
  font-size: 13px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px;
  font-size: 11.5px;
  color: var(--ink-muted);
  gap: 12px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  gap: 4px;
}
.pager button {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--r-s);
  width: 26px;
  height: 26px;
  color: var(--ink-muted);
}
.pager button.on {
  background: var(--brand);
  color: #05161c;
  border-color: var(--brand);
}
.pager button:disabled {
  opacity: 0.4;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
