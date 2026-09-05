<script setup lang="ts">
// Форма создания/редактирования устройства.
//
// Повторяет логику подтверждения конфликтов из текущего vanilla-фронтенда
// (frontend/static/app.js:saveForm) для консистентности UX: два специфичных
// кода 409-ошибки (см. backend/app/constants.py:ErrorCode) предлагают
// подтверждение через window.confirm() и повторную отправку с флагом, вместо
// того чтобы просто показать ошибку и заставить пользователя вводить всё заново.
import { computed, reactive, ref, watch } from 'vue'
import { ApiError, createResource, deleteResource, listResource, updateResource, ErrorCode } from '../api/client'
import { loadDeviceInterfaceDraftRows, persistDeviceInterfaces, validateInterfaceDraftRows } from '../api/deviceInterfaces'
import { computePortVlanOptions, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Device, DeviceModel, Rack, Room, OpenPort, OpenPortDraftRow, DeviceSoftware, SoftwareAssetDraftRow, InterfaceDraftRow, DeviceVLAN, DeviceVlanDraftRow, VLANDomainDeviceLink } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import DeviceVlanListEditor from './DeviceVlanListEditor.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { CatalogItem } from '../api/types'

const props = defineProps<{ device: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.device !== null)

function emptyForm() {
  return {
    device_type_id: '',
    manufacturer_id: '',
    model_id: '',
    serial_number: '',
    system_name: '',
    operating_system_id: '',
    embedded_os_id: '',
    siem_enabled: false,
    building_id: '',
    room_id: '',
    rack_id: '',
    rack_position: '',
    description: '',
  }
}

const form = reactive(emptyForm())

// Открытые порты устройства — staged локально, персистятся после сохранения самого устройства
// (нужен его id), по той же схеме delete-затем-recreate, что и для ВМ, см. VMFormModal.vue.
// OpenPortListEditor.vue переиспользован как есть (не знает про owner_type/owner_id).
const openPorts = ref<OpenPortDraftRow[]>([])
const softwareAssets = ref<SoftwareAssetDraftRow[]>([])
const interfaces = ref<InterfaceDraftRow[]>([])
const deviceVlans = ref<DeviceVlanDraftRow[]>([])
const memberDomainIds = ref<Set<string>>(new Set())
// Фикс п.1.3.8: домены VLAN на форме устройства — read-only список (галочки участников
// редактируются только в VLANDomainsPanel.vue, см. комментарий в DeviceVlanListEditor.vue), но
// нет способа стать участником домена, который только что создан ЗДЕСЬ ЖЕ, вложенным
// быстрым добавлением при заведении VLAN (domain_id -> nestedQuickAdd в quickAdd/schema.ts) —
// созданный VLAN принадлежит домену, в котором устройство не состоит, и availableVlans ниже его
// тут же отфильтровывает: VLAN "создался", но выбрать его для устройства не получалось.
// pendingDomainMemberships — домены, добавленные в САМ availableVlans локально (сразу же
// возвращает VLAN в список опций), и которые ещё предстоит закрепить на бэкенде при сохранении
// формы (см. submit() ниже) — тот же принцип staged-черновика, что у interfaces/deviceVlans и
// остальных вложенных списков этой формы, просто без отдельного UI-редактора для него.
const pendingDomainMemberships = ref<Set<string>>(new Set())
const deviceTypeVlanIds = ref<Set<string>>(new Set())
const loadingNested = ref(false)

// VLAN без домена доступны всем устройствам; доменные — только участникам домена (то же
// правило, что loadDeviceVlanEditor() в frontend/static/device-interfaces.js). pendingDomainMemberships
// объединяется с уже подтверждённым membership — см. комментарий к ней выше (фикс п.1.3.8).
const availableVlans = computed(() =>
  vlansStore.allDefinitions.filter((v) => !v.domain_id || memberDomainIds.value.has(v.domain_id) || pendingDomainMemberships.value.has(v.domain_id)),
)

// Опции для чекбоксов "VLAN на порту" (DeviceInterfacesEditor.vue) — НЕ то же самое, что
// availableVlans выше: тот отвечает "что можно НАЗНАЧИТЬ устройству" (фильтр по домену), этот —
// "что уже разрешено/назначено устройству, поэтому можно поставить на порт" (тип устройства ∪
// текущий черновик deviceVlans.value, ещё не обязательно сохранённый — так пользователь может
// одновременно добавить VLAN устройству и в этом же сохранении назначить его порту). См.
// api/portVlans.ts.
const portVlanOptions = computed(() =>
  computePortVlanOptions(
    vlansStore.allDefinitions,
    deviceTypeVlanIds.value,
    new Set(deviceVlans.value.map((r) => r.vlan_id).filter(Boolean)),
  ),
)

// Если VLAN устройства перестал быть опцией порта (пользователь снял его в блоке "VLAN
// устройства" или сменил тип устройства), убираем его и из vlan_ids уже заведённых портов —
// иначе сохранение упадёт 422 "VLAN не разрешён для типа данного устройства", а пользователь не
// поймёт, откуда ошибка. То же поведение, что syncDeviceVlanOptionsFromRows() в vanilla-версии.
//
// КРИТИЧНО: сравниваем НОВЫЙ список опций со СТАРЫМ (аргумент oldOptions от Vue) и трогаем
// только vlan_ids, которые были разрешены раньше и перестали быть разрешены сейчас — а не
// просто "не входят в текущий portVlanOptions". Первое срабатывание случится сразу после
// начальной загрузки устройства (oldOptions на этот момент — пустой массив от самого первого
// вычисления computed, ещё до загрузки), и разница будет пустой — начальная загрузка порт не
// тронет. Если бы вместо диффа проверялось только текущее значение, при первой же загрузке
// стёрлись бы vlan_ids, назначенные через /legacy, но не входящие в этот более узкий каталог
// (тип устройства ∪ уже назначенные) — ровно такой баг поймал регрессионный тест в
// DeviceFormModal.spec.ts ("не стирает VLAN интерфейса, назначенные через /legacy...").
watch(portVlanOptions, (options, oldOptions) => {
  const removedIds = new Set((oldOptions ?? []).filter((v) => !options.some((o) => o.id === v.id)).map((v) => v.id))
  if (!removedIds.size) return
  interfaces.value = interfaces.value.map((row) =>
    row.vlan_ids.some((id) => removedIds.has(id)) ? { ...row, vlan_ids: row.vlan_ids.filter((id) => !removedIds.has(id)) } : row,
  )
})

function toOpenPortDraftRow(x: OpenPort): OpenPortDraftRow {
  return {
    id: x.id,
    protocol_catalog_id: x.protocol_catalog_id ?? '',
    port: String(x.port),
    protocol: x.protocol ?? '',
    transport_protocol: x.transport_protocol,
    description: x.description ?? '',
  }
}

function toSoftwareDraftRow(x: DeviceSoftware): SoftwareAssetDraftRow {
  return { id: x.id, software_asset_id: x.software_asset_id, version: x.version ?? '' }
}

function toDeviceVlanDraftRow(x: DeviceVLAN): DeviceVlanDraftRow {
  return {
    id: x.id,
    vlan_id: x.vlan_id,
    ip_address: x.ip_address ?? '',
    prefix_length: x.prefix_length == null ? '' : String(x.prefix_length),
    is_management: x.is_management,
    description: x.description ?? '',
  }
}

watch(
  () => props.device,
  async (d) => {
    Object.assign(form, emptyForm())
    openPorts.value = []
    softwareAssets.value = []
    interfaces.value = []
    deviceVlans.value = []
    memberDomainIds.value = new Set()
    pendingDomainMemberships.value = new Set()
    deviceTypeVlanIds.value = new Set()
    if (d) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = d[key as keyof Device]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
    }
    if (!d) return
    loadingNested.value = true
    try {
      const [ports, software, ifaceRows, vlans, domainLinks, typeVlanIds] = await Promise.all([
        listResource<OpenPort>('open-ports', { owner_type: 'physical_device', owner_id: d.id, limit: 1000 }),
        listResource<DeviceSoftware>('device-software', { physical_device_id: d.id, limit: 1000 }),
        // Загрузка + сборка InterfaceDraftRow[] вынесена в api/deviceInterfaces.ts — тот же
        // помощник использует DevicePortsModal.vue (управление портами с экрана «Подключения»).
        loadDeviceInterfaceDraftRows(d.id),
        listResource<DeviceVLAN>('device-vlans', { physical_device_id: d.id, limit: 1000 }),
        listResource<VLANDomainDeviceLink>('vlan-domain-devices', { physical_device_id: d.id, limit: 1000 }),
        // Загружается атомарно вместе с interfaces/deviceVlans (не через отдельный watch на
        // form.device_type_id — см. ниже) именно для того, чтобы portVlanOptions выше не
        // пересчитался с неполными данными между двумя разными по времени загрузками.
        loadDeviceTypeVlanIds(d.device_type_id),
        vlansStore.ensureLoaded(),
      ])
      openPorts.value = ports.items.map(toOpenPortDraftRow)
      softwareAssets.value = software.items.map(toSoftwareDraftRow)
      interfaces.value = ifaceRows
      deviceVlans.value = vlans.items.map(toDeviceVlanDraftRow)
      memberDomainIds.value = new Set(domainLinks.items.map((l) => l.domain_id))
      deviceTypeVlanIds.value = typeVlanIds
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить открытые порты, ПО, интерфейсы и VLAN устройства'
    } finally {
      loadingNested.value = false
    }
  },
  { immediate: true },
)

// Каскадные списки: помещение — по зданию, стойка — по помещению. Тот же принцип, что связка
// building_id/room_id в фильтре DevicesView, только здесь ещё и сама форма подсказывает валидные
// сочетания вместо того, чтобы полагаться только на серверную валидацию.
const deviceModels = computed(() => catalogs.items['device-models'] as unknown as DeviceModel[])
const rooms = computed(() => catalogs.items['rooms'] as unknown as Room[])
const racks = computed(() => catalogs.items['racks'] as unknown as Rack[])

const filteredRooms = computed(() =>
  (rooms.value ?? []).filter((r) => !form.building_id || r.building_id === form.building_id),
)
const filteredRacks = computed(() =>
  (racks.value ?? []).filter((r) => !form.room_id || r.room_id === form.room_id),
)

// Фикс п.1.1: поиск вводом текста в "Помещение" (и заодно в соседних Здание/Стойка — те же
// select'ы в той же карточке, оставлять их нативными при уже поисковом "Помещении" рядом выглядело
// бы непоследовательно). catalogs.items[key] уже отсортирован (фикс п.4.2) — SearchableSelect
// сам ничего не пересортировывает, порядок options здесь и есть порядок в выпадающем списке.
const buildingOptions = computed(() => (catalogs.items['buildings'] ?? []).map((b) => ({ value: b.id, label: b.name })))
const roomOptions = computed(() => filteredRooms.value.map((r) => ({ value: r.id, label: r.name })))
const rackOptions = computed(() => filteredRacks.value.map((r) => ({ value: r.id, label: r.name })))

// п.3.6: поля "Тип устройства"/"Производитель"/"Модель" объединены в одно — это ОДИН select с
// двумя видами опций (группа "без модели" — просто тип, и группы моделей по производителю), а не
// три отдельных lookup'а. Значения опций закодированы как "type:<id>" / "model:<id>", т.к. один и
// тот же id мог бы иначе совпасть между разными сущностями.
//
// Компромисс этого объединения: раньше можно было явно указать производителя БЕЗ конкретной
// модели (три независимых поля) — при объединении в одно поле это больше не выразимо, т.к.
// единственный оставшийся способ задать производителя — выбрать модель, которая его несёт с
// собой. Это соответствует буквальной формулировке задачи ("одним полем"); если понадобится
// вернуть возможность "тип + производитель без модели", это отдельное решение, не совместимое с
// одним select'ом.
const modelGroups = computed(() => {
  const manufacturerName = (id: string | null) => (id ? catalogs.label('manufacturers', id, 'Без производителя') : 'Без производителя')
  const groups = new Map<string, { manufacturerId: string; manufacturerName: string; models: DeviceModel[] }>()
  for (const m of deviceModels.value ?? []) {
    const key = m.manufacturer_id ?? ''
    if (!groups.has(key)) groups.set(key, { manufacturerId: key, manufacturerName: manufacturerName(m.manufacturer_id), models: [] })
    groups.get(key)!.models.push(m)
  }
  return [...groups.values()]
    .map((g) => ({ ...g, models: [...g.models].sort((a, b) => a.model.localeCompare(b.model, 'ru')) }))
    .sort((a, b) => a.manufacturerName.localeCompare(b.manufacturerName, 'ru'))
})

// Фикс п.1.3.7: option внутри optgroup показывал только "голую" модель (WS-C2960-48TD-L) — это
// нормально смотрится, ПОКА список открыт (производитель виден как заголовок группы), но после
// выбора закрытый select показывает ТОЛЬКО текст выбранного option — заголовок optgroup при этом
// не отображается нигде. В закрытом виде терялось "какой это производитель" (напр. WS-C2960-48TD-L
// с равным успехом мог быть и Cisco, и OEM-реброндингом другого вендора). Префикс производителя
// прямо в тексте option чинит именно это, optgroup-группировку при этом не убираем — она всё ещё
// упрощает поиск глазами по алфавиту производителей, пока список открыт.
function modelOptionLabel(group: { manufacturerId: string; manufacturerName: string }, model: DeviceModel): string {
  return group.manufacturerId ? `${group.manufacturerName} ${model.model}` : model.model
}

const typeModelSelection = computed<string, string | undefined>({
  get() {
    if (form.model_id) return `model:${form.model_id}`
    if (form.device_type_id) return `type:${form.device_type_id}`
    return ''
  },
  set(value: string | undefined) {
    // value может прийти undefined: рантайм-директива vModelSelect у Vue берёт value ПЕРВОЙ
    // выбранной option (el.options, отфильтрованные по .selected) — если ни одна не выбрана
    // (например, тест или программный код выставил select.value на строку без совпадающей
    // option), массив выбранных пуст и selectedVal[0] оказывается undefined.
    const [kind, id] = (value ?? '').split(':')
    if (kind === 'model') {
      const model = deviceModels.value.find((m) => m.id === id)
      form.model_id = id
      form.device_type_id = model?.device_type_id ?? form.device_type_id
      form.manufacturer_id = model?.manufacturer_id ?? ''
    } else if (kind === 'type') {
      form.model_id = ''
      form.device_type_id = id
      form.manufacturer_id = ''
    } else {
      form.model_id = ''
      form.device_type_id = ''
      form.manufacturer_id = ''
    }
  },
})

// Квик-добавление модели устройства подставляет её id и синхронизирует device_type_id и
// manufacturer_id формы с моделью — то же самое, что делает setter typeModelSelection выше при
// выборе уже существующей модели, продублировано здесь явно, т.к. QuickAddButton отдаёт "сырой"
// CatalogItem напрямую в обход этого computed setter'а.
function onModelCreated(record: CatalogItem) {
  const model = record as unknown as DeviceModel
  form.model_id = model.id
  form.device_type_id = model.device_type_id ?? form.device_type_id
  form.manufacturer_id = model.manufacturer_id ?? ''
}

// Сброс зависимых полей при смене родителя — иначе можно оставить room_id от
// другого здания невидимым в списке, но по-прежнему отправляемым в payload.
watch(
  () => form.device_type_id,
  async (deviceTypeId) => {
    // loadingNested гвардит от повторной загрузки в момент самой начальной загрузки устройства
    // (там form.device_type_id меняется синхронно вместе с loadingNested=true в том же тике, а
    // deviceTypeVlanIds уже атомарно загружается в самом watch(props.device) выше) — этот watch
    // нужен только для случая, когда пользователь меняет тип устройства уже после загрузки.
    if (loadingNested.value) return
    try {
      deviceTypeVlanIds.value = await loadDeviceTypeVlanIds(deviceTypeId)
    } catch (err) {
      // Не даём упасть необработанным отклонением промиса — просто оставляем прежний список
      // допустимых VLAN порта и показываем ошибку, как и везде в этой форме.
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить допустимые VLAN для типа устройства'
    }
  },
)
watch(
  () => form.building_id,
  () => {
    if (!filteredRooms.value.some((r) => r.id === form.room_id)) form.room_id = ''
  },
)
watch(
  () => form.room_id,
  () => {
    if (!filteredRacks.value.some((r) => r.id === form.rack_id)) form.rack_id = ''
  },
)

function toPayload(extra?: Record<string, unknown>) {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return { ...payload, ...extra }
}

// п.3.1: квик-добавление помещения/стойки синхронизирует и родительские поля формы — иначе
// созданная запись могла бы не попасть в filteredRooms/filteredRacks (фильтр по
// building_id/room_id, см. выше) и пропасть из виду в своём же select'е сразу после создания.
function onRoomCreated(record: CatalogItem) {
  const room = record as unknown as Room
  form.building_id = room.building_id
  form.room_id = room.id
}
function onRackCreated(record: CatalogItem) {
  const rack = record as unknown as Rack
  const room = catalogs.indexOf('rooms').get(rack.room_id) as unknown as Room | undefined
  if (room) form.building_id = room.building_id
  form.room_id = rack.room_id
  form.rack_id = rack.id
}

// Фикс п.1.3.8: см. комментарий у pendingDomainMemberships/availableVlans выше. domain_id может
// отсутствовать (VLAN без домена — общедоступен всем устройствам без каких-либо условий, тут
// добавлять нечего) или уже быть в числе подтверждённых участников (обычный, самый частый
// случай — тут тоже добавлять нечего, только оверхед на бэкенде при сохранении).
function onVlanCreated(record: CatalogItem) {
  vlansStore.reload()
  const domainId = (record as { domain_id?: string | null }).domain_id
  if (domainId && !memberDomainIds.value.has(domainId)) {
    pendingDomainMemberships.value = new Set([...pendingDomainMemberships.value, domainId])
  }
}

// Delete-затем-recreate — тот же приём и то же обоснование (маленькие списки, простота важнее
// diff-логики), что persistVmIps()/persistOpenPorts() в VMFormModal.vue.
async function persistOpenPorts(deviceId: string) {
  const existing = await listResource<OpenPort>('open-ports', { owner_type: 'physical_device', owner_id: deviceId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('open-ports', old.id)
  }
  for (const row of openPorts.value) {
    if (!row.port.trim()) continue // port NOT NULL на бэкенде, см. VMFormModal.vue
    await createResource<OpenPort>('open-ports', {
      owner_type: 'physical_device',
      owner_id: deviceId,
      protocol_catalog_id: row.protocol_catalog_id || null,
      port: Number(row.port),
      protocol: row.protocol || null,
      transport_protocol: row.transport_protocol || 'TCP',
      description: row.description || null,
    })
  }
}

async function persistSoftwareAssets(deviceId: string) {
  const existing = await listResource<DeviceSoftware>('device-software', { physical_device_id: deviceId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('device-software', old.id)
  }
  for (const row of softwareAssets.value) {
    if (!row.software_asset_id) continue
    await createResource<DeviceSoftware>('device-software', {
      physical_device_id: deviceId,
      software_asset_id: row.software_asset_id,
      version: row.version || null,
    })
  }
}

// Delete-затем-recreate (НЕ через атомарный PUT, в отличие от persistInterfaces ниже) — тем же
// приёмом, что и в vanilla-версии (saveDeviceVlans в frontend/static/device-interfaces.js).
// Фикс п.1.3.8: закрепляет на бэкенде членство устройства в доменах, добавленных локально через
// onVlanCreated() выше (см. её комментарий и комментарий к pendingDomainMemberships). ДО
// persistDeviceVlans() ниже — _validate_physical_device_vlan в backend/app/services/crud.py
// проверяет членство устройства в домене VLAN при сохранении device-vlans и отклоняет запись
// с 422 "Устройство не включено в домен этого VLAN", если членства ещё нет.
async function persistPendingDomainMemberships(deviceId: string) {
  for (const domainId of pendingDomainMemberships.value) {
    await createResource('vlan-domain-devices', { physical_device_id: deviceId, domain_id: domainId })
  }
}

async function persistDeviceVlans(deviceId: string) {
  const existing = await listResource<DeviceVLAN>('device-vlans', { physical_device_id: deviceId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('device-vlans', old.id)
  }
  for (const row of deviceVlans.value) {
    if (!row.vlan_id) continue
    await createResource<DeviceVLAN>('device-vlans', {
      physical_device_id: deviceId,
      vlan_id: row.vlan_id,
      ip_address: row.ip_address || null,
      prefix_length: row.prefix_length === '' ? null : Number(row.prefix_length),
      is_management: row.is_management,
      description: row.description || null,
    })
  }
}

async function submit() {
  errorMessage.value = null
  if (!form.device_type_id) {
    errorMessage.value = 'Укажите тип устройства.'
    return
  }
  if (!form.serial_number.trim()) {
    errorMessage.value = 'Укажите серийный номер.'
    return
  }
  const interfaceError = validateInterfaceDraftRows(interfaces.value)
  if (interfaceError) {
    errorMessage.value = interfaceError
    return
  }

  saving.value = true
  try {
    let extra: Record<string, unknown> | undefined
    // До трёх попыток: обычная отправка, затем до двух ре-отправок с флагами
    // подтверждения, если пользователь согласился на диалоге.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const payload = toPayload(extra)
        const saved = isEdit.value
          ? await updateResource<Device>('devices', props.device!.id, payload)
          : await createResource<Device>('devices', payload)
        await persistOpenPorts(saved.id)
        await persistSoftwareAssets(saved.id)
        await persistPendingDomainMemberships(saved.id)
        // persistDeviceVlans ДО persistDeviceInterfaces (не как раньше) — sync_interfaces на
        // бэкенде проверяет vlan_ids порта против уже сохранённых в БД PhysicalDeviceVLAN (см.
        // allowed_vlans в backend/app/services/crud.py). Если VLAN только что добавлен в блок
        // "VLAN устройства" и тут же назначен порту в этом же сохранении, к моменту проверки он
        // должен уже быть в БД — иначе 422 "VLAN не разрешён" на ровном месте для пользователя.
        await persistDeviceVlans(saved.id)
        // Атомарный PUT (не через generic createResource/deleteResource, как выше) — см.
        // api/deviceInterfaces.ts:persistDeviceInterfaces.
        const { items: savedInterfaces } = await persistDeviceInterfaces(saved.id, interfaces.value)
        // Фикс п.3.1: без этого catalogs.items['interfaces'] не узнаёт о только что
        // сохранённых портах устройства (persistDeviceInterfaces — чистый API-вызов, сам кэш
        // каталогов не трогает по дизайну, см. её комментарий), и поле "Порт" в форме
        // подключения (ConnectionFormModal.vue, читает ровно этот кэш) оставалось пустым для
        // нового устройства до жёсткой перезагрузки страницы, обнуляющей кэш и вызывающей
        // catalogs.reload() заново. DevicePortsModal.vue делает этот же вызов уже сейчас —
        // здесь его просто не было для основного пути создания/редактирования устройства.
        catalogs.replaceDeviceInterfaces(saved.id, savedInterfaces)
        emit('saved', saved)
        return
      } catch (err) {
        if (err instanceof ApiError && err.code === ErrorCode.DUPLICATE_SYSTEM_NAME && confirm(err.message + '\n\nОК — сохранить дубликат.')) {
          extra = { ...extra, confirm_system_name_duplicate: true }
          continue
        }
        if (err instanceof ApiError && err.code === ErrorCode.RACK_POSITION_OCCUPIED && confirm(err.message)) {
          extra = { ...extra, confirm_rack_position_reassign: true }
          continue
        }
        throw err
      }
    }
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить устройство'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать устройство' : 'Добавить устройство' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form class="form-grid" @submit.prevent="submit">
        <!-- п.3.6: три поля (Тип устройства/Производитель/Модель) объединены в одно — единственный
             select с опциями "голых" типов (без модели) и моделей, сгруппированных по
             производителю. См. typeModelSelection/modelGroups в <script setup>. -->
        <label class="field field-wide">
          <span>Тип / производитель / модель *</span>
          <div class="lookup-row">
            <select v-model="typeModelSelection" required>
              <option value="">— выберите —</option>
              <optgroup label="Тип устройства (без конкретной модели)">
                <option v-for="t in catalogs.items['device-types'] ?? []" :key="t.id" :value="`type:${t.id}`">{{ t.name }}</option>
              </optgroup>
              <optgroup v-for="g in modelGroups" :key="g.manufacturerId" :label="g.manufacturerName">
                <option v-for="m in g.models" :key="m.id" :value="`model:${m.id}`">{{ modelOptionLabel(g, m) }}</option>
              </optgroup>
            </select>
            <QuickAddButton resource="device-models" title="Модель устройства" @created="onModelCreated" />
          </div>
        </label>

        <label class="field">
          <span>Серийный номер *</span>
          <input v-model.trim="form.serial_number" v-truncate-tooltip="form.serial_number" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Системное имя</span>
          <input v-model.trim="form.system_name" v-truncate-tooltip="form.system_name" type="text" maxlength="255" />
        </label>

        <label class="field">
          <span>Операционная система</span>
          <div class="lookup-row">
            <select v-model="form.operating_system_id">
              <option value="">— не указана —</option>
              <option v-for="os in catalogs.items['operating-systems'] ?? []" :key="os.id" :value="os.id">
                {{ catalogs.label('operating-systems', os.id) }}
              </option>
            </select>
            <QuickAddButton resource="operating-systems" title="Операционная система" @created="(r) => (form.operating_system_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Встроенная ОС (для сетевого оборудования)</span>
          <div class="lookup-row">
            <select v-model="form.embedded_os_id">
              <option value="">— не указана —</option>
              <option v-for="os in catalogs.items['embedded-os'] ?? []" :key="os.id" :value="os.id">
                {{ catalogs.label('embedded-os', os.id) }}
              </option>
            </select>
            <QuickAddButton resource="embedded-os" title="Встроенная ОС" @created="(r) => (form.embedded_os_id = r.id)" />
          </div>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.siem_enabled" type="checkbox" />
          <span>Отправляет события в SIEM</span>
        </label>

        <label class="field">
          <span>Здание</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.building_id" :options="buildingOptions" placeholder="— не указано —" />
            <QuickAddButton resource="buildings" title="Здание" @created="(r) => (form.building_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Помещение</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.room_id" :options="roomOptions" :disabled="!form.building_id" placeholder="— не указано —" />
            <QuickAddButton resource="rooms" title="Помещение" @created="onRoomCreated" />
          </div>
        </label>

        <label class="field">
          <span>Стойка</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.rack_id" :options="rackOptions" :disabled="!form.room_id" placeholder="— не указана —" />
            <QuickAddButton resource="racks" title="Стойка" @created="onRackCreated" />
          </div>
        </label>

        <label class="field">
          <span>Позиция в стойке</span>
          <input v-model.trim="form.rack_position" v-truncate-tooltip="form.rack_position" type="text" placeholder="напр. 12U" maxlength="50" />
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <p v-if="loadingNested" class="loading-hint field-wide">Загрузка портов, ПО, интерфейсов и VLAN…</p>
        <OpenPortListEditor v-if="!loadingNested" v-model="openPorts" :catalog-entries="catalogs.protocolPortCatalog" />
        <SoftwareAssetListEditor v-if="!loadingNested" v-model="softwareAssets" :catalog-entries="catalogs.items['software-assets'] ?? []" />
        <DeviceInterfacesEditor
          v-if="!loadingNested"
          v-model="interfaces"
          :type-options="catalogs.items['interface-types'] ?? []"
          :speed-options="catalogs.items['interface-speeds'] ?? []"
          :vlan-options="portVlanOptions"
        />
        <DeviceVlanListEditor v-if="!loadingNested" v-model="deviceVlans" :vlan-options="availableVlans" @vlan-created="onVlanCreated" />
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
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
  /* п.1.3: форма устройства заметно длиннее большинства остальных модалок (порты,
     VLAN, программные активы и т.п.) — фиксированные 640px были тесноваты. clamp()
     держит текущие 640px как нижнюю границу (не уже, чем сейчас, на узких десктопных
     экранах — width: 100% и так сжимает модалку на мобильных, эта нижняя граница
     там ни на что не влияет), масштабируется как ~50% ширины окна на типичных
     мониторах и не раздувается сверх 1100px на сверхширoких. */
  max-width: clamp(640px, 50vw, 1100px);
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
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
  /* п.3.2: без min-width:0 ячейка CSS-грида не сжимается ниже intrinsic-ширины своего
     содержимого — длинный текст в select/input (например, длинное имя помещения) распирал
     ячейку шире её грид-трека и вылезал за пределы скруглённой подложки модалки (.modal). */
  min-width: 0;
}
.field-wide {
  grid-column: 1 / -1;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
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
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.field select:disabled {
  opacity: 0.5;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12.5px;
}
.loading-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
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
