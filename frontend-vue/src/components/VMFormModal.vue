<script setup lang="ts">
// hypervisor_os_id НЕ отправляется пользователем — бэкенд всегда пересчитывает его
// сам из ОС выбранного физического хоста (см. backend/app/services/crud/generic.py:
// create_resource/update_resource, VirtualMachine: "data['hypervisor_os_id'] = host.
// operating_system_id..."). Поле показано только как read-only предпросмотр того,
// что реально запишется. Хост-устройство дополнительно отфильтровано на клиенте
// до серверов/СХД (validate_vm_host в services/validation.py отклонит остальные
// типы с 422) — фильтрация здесь не замена серверной проверке, а просто не даёт
// пользователю выбрать заведомо невалидный вариант.
import { computed, reactive, ref, watch, useId } from 'vue'
import { createResource, listAllResource } from '../api/client'
import { loadNestedList, type NestedListResult, type NestedLoadIssue } from '../composables/loadNestedList'
import { syncVmDeployedSoftware, syncVmIpAddresses, syncVmOpenPorts } from '../api/vmNestedLists'
import type { VirtualMachine, Device, IPAddress, OpenPort, DeployedSoftware, VmIpDraftRow, OpenPortDraftRow, SoftwareAssetDraftRow } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useFormPreferencesStore } from '../stores/formPreferences'
import { filterHostDevices } from '../utils/deviceFilters'
import { isValidIPv4, isValidPrefixLength } from '../utils/ipValidation'
import { duplicatePortNumbers, sortOpenPortRows } from '../utils/openPorts'
import { toIpDraftRow, toOpenPortDraftRow, toSoftwareDraftRow } from '../utils/vmDraftRows'
import { sortOptionsByLabel } from '../utils/selectOptions'
import VmIpListEditor from './VmIpListEditor.vue'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import DataLoadNotice from './DataLoadNotice.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import BaseModal from './BaseModal.vue'
import { stripIds } from '../utils/copyEntity'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'
import { useStaleRecordGuard } from '../composables/useStaleRecordGuard'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ vm: VirtualMachine | null; copyFrom?: VirtualMachine | null }>()
const emit = defineEmits<{ close: []; saved: [vm: VirtualMachine] }>()
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const stale = useStaleRecordGuard({ resource: 'vms', record: () => props.vm, close: () => emit('close') })
const formPreferences = useFormPreferencesStore() // общий порог сворачивания списка открытых портов (из «Настроек»)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.vm !== null)

function emptyForm() {
  return {
    name: '',
    operating_system_id: '',
    physical_device_id: '',
    purpose: '',
    description: '',
  }
}
const form = reactive(emptyForm())

// Staged локально до сохранения самой ВМ — так же, как vmIpRows/vmOpenPortRows
// в vanilla-версии (до 2.60.0): для НОВОЙ ВМ строки можно
// заполнить сразу в той же форме, ещё до того, как у записи появится id, а
// реально отправить на сервер только после того, как известен id (см. submit()).
const vmIps = ref<VmIpDraftRow[]>([])
const openPorts = ref<OpenPortDraftRow[]>([])
const softwareAssets = ref<SoftwareAssetDraftRow[]>([])
const loadingNested = ref(false)

// Три вложенных списка сохраняются целиком: сервер удаляет записи, которых нет в присланном списке. Поэтому список, который не
// загрузился или загружен не целиком (issue), НЕ показывается и НЕ отправляется: иначе пустой редактор (или его усечённая часть)
// при сохранении стёр бы живые данные ВМ. Каждый список независим: сбой IP-адресов не мешает править порты и ПО.
type NestedKey = 'ips' | 'ports' | 'software'
const NESTED_KEYS: readonly NestedKey[] = ['ips', 'ports', 'software']
const NESTED_WHAT: Record<NestedKey, string> = { ips: 'IP-адресов ВМ', ports: 'открытых портов ВМ', software: 'ПО ВМ' }
const nestedIssues = reactive<Record<NestedKey, NestedLoadIssue | null>>({ ips: null, ports: null, software: null })

watch(
  () => props.vm ?? props.copyFrom ?? null,
  async (source) => {
    // Аудит fix/usability-batch4 (находка №5): см. подробный комментарий в DeviceFormModal.vue.
    if (props.vm && props.copyFrom) {
      console.warn('VMFormModal: одновременно переданы vm и copyFrom — используется vm (режим редактирования)')
    }
    const isCopy = !props.vm && !!props.copyFrom
    Object.assign(form, emptyForm())
    vmIps.value = []
    openPorts.value = []
    softwareAssets.value = []
    for (const key of NESTED_KEYS) nestedIssues[key] = null
    if (!source) return
    form.name = isCopy ? '' : source.name // VirtualMachine.name уникален (backend/app/models.py) — копию с тем же именем не сохранить
    form.operating_system_id = source.operating_system_id ?? ''
    form.physical_device_id = source.physical_device_id ?? ''
    form.purpose = source.purpose ?? ''
    form.description = source.description ?? ''

    await loadNested(source, isCopy, NESTED_KEYS)
  },
  { immediate: true },
)

/** Загружает один вложенный список в черновик и запоминает, можно ли его сохранять (nestedIssues). Список с проблемой остаётся пустым. */
async function loadNestedKey(key: NestedKey, source: VirtualMachine, isCopy: boolean): Promise<NestedListResult<unknown>> {
  const owner = { owner_type: 'virtual_machine', owner_id: source.id }
  const what = NESTED_WHAT[key]
  let result: NestedListResult<unknown>
  if (key === 'ips') {
    const r = await loadNestedList(() => listAllResource<IPAddress>('ip-addresses', owner), what)
    const rows = r.items.map(toIpDraftRow)
    vmIps.value = isCopy ? stripIds(rows) : rows
    result = r
  } else if (key === 'ports') {
    const r = await loadNestedList(() => listAllResource<OpenPort>('open-ports', owner), what)
    // Бэкенд отдаёт open-ports без сортировки по порту (list_resource) — упорядочиваем при загрузке,
    // чтобы и ранее сохранённые ВМ открывались с портами по возрастанию.
    const rows = r.items.map(toOpenPortDraftRow)
    openPorts.value = sortOpenPortRows(isCopy ? stripIds(rows) : rows, catalogs.protocolPortCatalog)
    result = r
  } else {
    const r = await loadNestedList(() => listAllResource<DeployedSoftware>('deployed-software', owner), what)
    const rows = r.items.map(toSoftwareDraftRow)
    softwareAssets.value = isCopy ? stripIds(rows) : rows
    result = r
  }
  nestedIssues[key] = result.issue
  return result
}

/** Грузит перечисленные списки параллельно; пока идёт загрузка, «Сохранить» недоступна (см. submit). Первую ошибку показывает форма. */
async function loadNested(source: VirtualMachine, isCopy: boolean, keys: readonly NestedKey[]) {
  loadingNested.value = true
  try {
    const results = await Promise.all(keys.map((key) => loadNestedKey(key, source, isCopy)))
    const failed = results.find((r) => r.issue?.kind === 'failed')
    if (failed) errorMessage.value = failed.error instanceof Error ? failed.error.message : 'Не удалось загрузить IP-адреса, открытые порты и ПО ВМ'
  } finally {
    loadingNested.value = false
  }
}

/** «Повторить загрузку»: перечитываются только списки, которые не загрузились; основные поля и уже загруженные списки не трогаются. */
async function retryNested() {
  const source = props.vm ?? props.copyFrom ?? null
  if (!source) return
  errorMessage.value = null
  await loadNested(
    source,
    !props.vm && !!props.copyFrom,
    NESTED_KEYS.filter((key) => nestedIssues[key]?.kind === 'failed'),
  )
}

/** Свойства DataLoadNotice для списка с проблемой загрузки. */
function noticeProps(key: NestedKey) {
  const issue = nestedIssues[key]
  return {
    kind: issue?.kind ?? 'failed',
    what: NESTED_WHAT[key],
    loaded: issue?.kind === 'partial' ? issue.loaded : undefined,
    total: issue?.kind === 'partial' ? issue.total : undefined,
  } as const
}

const hostCandidates = computed<Device[]>(() => filterHostDevices(devicesStore.all, catalogs))

// «Операционная система» и «Физическое устройство (хост)» — SearchableSelect (поиск вводом текста).
// Порядок опций задаём здесь, а не берём из источника: справочник ОС в сторе отсортирован только при
// загрузке (и по полям name/version, а не по показываемой подписи), а devicesStore.all — в порядке
// ответа API (серверной сортировки у GET /devices нет, см. stores/devices.ts). Правило сортировки —
// общее для всех выпадающих списков, см. utils/selectOptions.ts.
const operatingSystemOptions = computed(() =>
  sortOptionsByLabel((catalogs.items['operating-systems'] ?? []).map((os) => ({ value: os.id, label: catalogs.label('operating-systems', os.id) }))),
)

// Хост, уже выбранный у ВМ, но не проходящий фильтр хостов (у устройства сменили тип, фильтр
// filterHostDevices смотрит на название типа), остаётся в списке с пометкой, пока он выбран. Без этого
// SearchableSelect не нашёл бы подпись выбранного значения и показал пустое поле, хотя physical_device_id
// по-прежнему уходит на сервер — пользователь видел бы пустой «Хост» и непонятную ошибку 422 при сохранении.
// Пометка нейтральная («вне списка хостов»): допустимость хоста окончательно решает сервер
// (validate_vm_host), а не этот клиентский фильтр. Выбрали другой хост — «лишний» вариант исчезает.
const OUTSIDE_HOST_LIST_SUFFIX = ' (вне списка хостов)'
const hostLabel = (d: Device): string => d.system_name || d.serial_number
const hostOptions = computed(() => {
  const options = hostCandidates.value.map((d) => ({ value: d.id, label: hostLabel(d) }))
  const selectedId = form.physical_device_id
  if (selectedId && !options.some((o) => o.value === selectedId)) {
    const selected = devicesStore.all.find((d) => d.id === selectedId)
    if (selected) options.push({ value: selected.id, label: hostLabel(selected) + OUTSIDE_HOST_LIST_SUFFIX })
  }
  return sortOptionsByLabel(options)
})

const derivedHypervisor = computed(() => {
  if (!form.physical_device_id) return null
  const host = devicesStore.all.find((d) => d.id === form.physical_device_id)
  if (!host?.operating_system_id) return 'у хоста не указана ОС'
  return catalogs.label('operating-systems', host.operating_system_id)
})

function toPayload() {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return payload
}

// IP-адреса, открытые порты и программные активы сохраняются одинаково: один атомарный PUT на
// список (/vms/{id}/ip-addresses | /open-ports | /deployed-software, см. api/vmNestedLists.ts).
// Сервер сравнивает список с БД по id: строки с id обновляются на месте, новые создаются, убранные в
// форме удаляются — id и дата создания сохранённых записей не меняются, в журнал аудита попадает
// только реальное изменение, а ошибка в любой строке откатывает весь список. Порядок строк в запросе
// значения не имеет: при следующем открытии формы список упорядочивает загрузчик (см. watch выше).
//
// Новой ВМ (создание или копия) синхронизировать нечего, если ни одна строка не заполнена, —
// лишний запрос не отправляется. Для существующей ВМ пустой список отправляется всегда: так
// удаляются записи, которые пользователь убрал из формы.
//
// Исключение — список, который не загрузился или загружен не целиком (nestedIssues): он в форме не показан, и его «пустота» — не
// решение пользователя, а отсутствие данных. PUT с таким списком удалил бы все (или все невидимые) записи ВМ, поэтому не отправляется.
async function persistVmIps(vmId: string) {
  if (nestedIssues.ips) return
  if (!isEdit.value && !vmIps.value.some((row) => row.ip_address.trim())) return
  await syncVmIpAddresses(vmId, vmIps.value)
}

async function persistOpenPorts(vmId: string) {
  if (nestedIssues.ports) return
  if (!isEdit.value && !openPorts.value.some((row) => row.protocol_catalog_id)) return
  await syncVmOpenPorts(vmId, openPorts.value)
}

async function persistSoftwareAssets(vmId: string) {
  if (nestedIssues.software) return
  if (!isEdit.value && !softwareAssets.value.some((row) => row.software_asset_id)) return
  await syncVmDeployedSoftware(vmId, softwareAssets.value)
}

async function submit() {
  // Пока списки грузятся, они пусты, а не «убраны пользователем»: сохранение в этот момент стёрло бы их на сервере.
  if (readOnly.value || loadingNested.value) return
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите название виртуальной машины.'
    return
  }
  // Фикс п.3: "в поле 'IP-адреса виртуальной машины' можно ввести любые данные... необходимо
  // применить исправление ко всем полям с ip" — та же валидация, что и в DeviceFormModal.vue.
  for (const row of vmIps.value) {
    if (!isValidIPv4(row.ip_address)) {
      errorMessage.value = `Некорректный IP-адрес «${row.ip_address}».`
      return
    }
    if (!isValidPrefixLength(row.prefix_length)) {
      errorMessage.value = `Некорректный префикс «${row.prefix_length}» — допустимо 0-32.`
      return
    }
  }
  const duplicatePorts = duplicatePortNumbers(openPorts.value, catalogs.protocolPortCatalog)
  if (duplicatePorts.length) {
    errorMessage.value = `Номера открытых портов не должны повторяться: ${duplicatePorts.join(', ')}.`
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    const saved = isEdit.value ? await stale.update<VirtualMachine>(props.vm!.id, payload) : await createResource<VirtualMachine>('vms', payload)
    if (!saved) return // при конфликте версий пользователь отказался сохранять
    await persistVmIps(saved.id)
    await persistOpenPorts(saved.id)
    await persistSoftwareAssets(saved.id)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить виртуальную машину'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseModal @close="emit('close')">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ isEdit ? 'Редактировать виртуальную машину' : 'Добавить виртуальную машину' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <fieldset class="readonly-fieldset" :disabled="readOnly">
        <form class="form-grid" @submit.prevent="submit">
          <label class="field field-wide">
            <span>Название *</span>
            <input v-model.trim="form.name" type="text" required maxlength="255" />
          </label>

          <label class="field">
            <span>Операционная система</span>
            <div class="lookup-row">
              <SearchableSelect v-model="form.operating_system_id" :options="operatingSystemOptions" placeholder="— не указана —" />
              <QuickAddButton resource="operating-systems" title="Операционная система" @created="(r) => (form.operating_system_id = r.id)" />
            </div>
          </label>

          <label class="field">
            <span>Физическое устройство (хост)</span>
            <SearchableSelect v-model="form.physical_device_id" :options="hostOptions" placeholder="— не указано —" />
            <small v-if="!hostCandidates.length" class="hint-small">Нет доступных серверов/СХД в реестре устройств.</small>
          </label>

          <label class="field">
            <span>Гипервизор (определяется автоматически по хосту)</span>
            <input :value="derivedHypervisor ?? '—'" type="text" disabled />
          </label>

          <label class="field field-wide">
            <span>Целевое назначение</span>
            <textarea v-model.trim="form.purpose" rows="2" maxlength="2000"></textarea>
          </label>

          <label class="field field-wide">
            <span>Описание</span>
            <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
          </label>

          <p v-if="loadingNested" class="loading-hint field-wide">Загрузка IP-адресов, открытых портов и ПО…</p>
          <template v-else>
            <DataLoadNotice v-if="nestedIssues.ips" class="field-wide" v-bind="noticeProps('ips')" @retry="retryNested" />
            <VmIpListEditor v-else v-model="vmIps" />
            <DataLoadNotice v-if="nestedIssues.ports" class="field-wide" v-bind="noticeProps('ports')" @retry="retryNested" />
            <OpenPortListEditor
              v-else
              v-model="openPorts"
              :catalog-entries="catalogs.protocolPortCatalog"
              :collapse-after="formPreferences.collapseRows"
              sorted-unique
            />
            <DataLoadNotice v-if="nestedIssues.software" class="field-wide" v-bind="noticeProps('software')" @retry="retryNested" />
            <SoftwareAssetListEditor v-else v-model="softwareAssets" :catalog-entries="catalogs.items['software-assets'] ?? []" />
          </template>
        </form>
      </fieldset>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving || loadingNested" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.modal {
  width: 100%;
  /* Фикс п.4.1: было 600px фиксированных — ширина окна редактирования ВМ должна быть как у
     "Добавления устройства" (DeviceFormModal.vue), см. её комментарий про clamp(). */
  max-width: clamp(640px, 50vw, 1100px);
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.loading-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
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
  margin-bottom: 14px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field-wide {
  grid-column: 1 / -1;
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
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.field input:disabled {
  opacity: 0.7;
  font-style: italic;
}
.hint-small {
  color: var(--status-warn);
  font-size: 10.5px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
