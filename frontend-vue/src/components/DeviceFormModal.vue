<script setup lang="ts">
// Форма создания/редактирования устройства.
//
// Повторяет логику подтверждения конфликтов из текущего vanilla-фронтенда
// (frontend/static/app.js:saveForm) для консистентности UX: два специфичных
// кода 409-ошибки (см. backend/app/constants.py:ErrorCode) предлагают
// подтверждение через window.confirm() и повторную отправку с флагом, вместо
// того чтобы просто показать ошибку и заставить пользователя вводить всё заново.
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { ApiError, createResource, listResource, updateResource, ErrorCode } from '../api/client'
import { syncDeviceDeployedSoftware } from '../api/deviceDeployedSoftware'
import { persistDeviceVlans } from '../api/deviceVlans'
import { loadDeviceInterfaceDraftRows, loadDeviceInterfaceGroups, persistDeviceInterfaces, validateInterfaceDraftRows } from '../api/deviceInterfaces'
import { stripSubinterfaceIds, subinterfaceVlanRemovalMessage } from '../utils/subinterfaces'
import { cloneGroupsForCopy, validateInterfaceGroups } from '../utils/interfaceGroups'
import { isValidIPv4, isValidPrefixLength } from '../utils/ipValidation'
import { computePortVlanOptions, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Device, DeviceMemberDomain, DeviceModel, Rack, Room, DeployedSoftware, SoftwareAssetDraftRow, InterfaceDraftRow, InterfaceGroupDraft, DeviceVLAN, DeviceVlanDraftRow, VLANDomainDeviceLink, PortConflictInfo } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useFormPreferencesStore } from '../stores/formPreferences'
import { useConnectionsStore } from '../stores/connections'
import { useDevicesStore } from '../stores/devices'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { usePortSyncPlanRequest } from '../composables/usePortSyncPlanRequest'
import { findPortSyncNotice } from '../utils/portSyncNotice'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import DeviceVlanListEditor from './DeviceVlanListEditor.vue'
import DeviceIconPicker from './DeviceIconPicker.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'
import type { CatalogItem } from '../api/types'
import { stripIds } from '../utils/copyEntity'
import { duplicateVlansMessage, sortDeviceVlanRows } from '../utils/deviceVlans'
import { filterVlansForDeviceDomains, groupVlanRemovalMessage, mergeDomainVlansIntoDraft, reconcileVlanIds, removeDomainVlansFromDraft } from '../utils/vlan'
import { buildPortConflictNotice, computePortConflicts, snapshotPortConfigs, type PortConfig, type PortRowLike } from '../utils/portConflicts'
import { fetchDeviceInterfaceConnections, type DeviceInterfaceConnection } from '../api/deviceConnectivity'
import { attachConnectionDrafts, changedConnectionRowIds, hasConnectionChanges, snapshotConnections, validateConnectionDrafts, type ConnectionBaseline } from '../utils/interfaceConnections'

const props = defineProps<{ device: Device | null; copyFrom?: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const vlanDomainsStore = useVLANDomainsStore()
const formPreferences = useFormPreferencesStore()
const connectionsStore = useConnectionsStore()
const devicesStore = useDevicesStore()
const { notify, notifyError } = useToast()
const portSyncPlan = usePortSyncPlanRequest()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
// Устройство, которое ЭТА форма уже создала, но не смогла сохранить целиком: после createResource идёт
// несколько отдельных запросов (ПО, домены, VLAN, порты и подключения), и сбой любого из них оставляет
// устройство в БД. Пока оно задано, повторное «Сохранить» ОБНОВЛЯЕТ его — иначе второй POST создал бы дубль
// (или упёрся бы в уникальность серийного номера), а пользователь не смог бы исправить данные и дозаписать.
const createdDevice = ref<Device | null>(null)
// Домены, в которые устройство уже включено запросом этой формы: повтор после сбоя не должен отправлять
// POST vlan-domain-devices второй раз (связь уже создана).
const joinedDomainIds = new Set<string>()
const existingDeviceId = computed(() => props.device?.id ?? createdDevice.value?.id ?? null)
const isEdit = computed(() => existingDeviceId.value !== null)

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
    // Необязательный блок "Сертификат ОАЦ" (models.PhysicalDevice) — заполняется, если на
    // устройстве установлено сертифицированное средство криптографической защиты (см. также
    // CryptoProtectionMeans.physical_device_id, привязываемый со стороны справочника СКЗИ в
    // "Другие справочники"). Оба поля независимы: пара "заполнено/не заполнено" не проверяется.
    oac_certificate_number: '',
    oac_certificate_registry_date: '',
    // Раздел 4.3 ТЗ: ручное переопределение автогенерируемой иконки диаграммы для КОНКРЕТНОГО
    // устройства (побеждает переопределение на уровне DeviceModel, если оно тоже задано).
    diagram_icon_id: '',
  }
}

const form = reactive(emptyForm())

// Фикс п.1.4 (батч4): открытые порты больше не самостоятельный список уровня устройства — теперь
// это InterfaceDraftRow.open_ports внутри каждой строки interfaces (см. её комментарий в
// types.ts) и персистятся атомарно вместе с интерфейсом через persistDeviceInterfaces().
const softwareAssets = ref<SoftwareAssetDraftRow[]>([])
const interfaces = ref<InterfaceDraftRow[]>([])
// Редактор портов: перед записью проверяет расхождения с соседями (reviewNeighborMismatches).
const interfacesEditor = ref<InstanceType<typeof DeviceInterfacesEditor> | null>(null)
// Группы портов (InterfaceGroupsPanel.vue внутри DeviceInterfacesEditor.vue): общие режим порта/VLAN,
// IP и открытые порты для нескольких портов. Грузятся с портами и сохраняются с ними одним PUT.
const interfaceGroups = ref<InterfaceGroupDraft[]>([])
const deviceVlans = ref<DeviceVlanDraftRow[]>([])
// Блок «VLAN устройства»: форма раскрывает его, когда ошибка сохранения относится к строке, скрытой сворачиванием.
const vlanEditor = ref<InstanceType<typeof DeviceVlanListEditor> | null>(null)
// Пункт 5: конфигурация (Управление/Передача данных/режим порта) уже сохранённых портов на момент
// открытия формы — по ней при сохранении определяется, что конфигурация порта с расхождением
// относительно соседа сохраняется ВПЕРВЫЕ (см. utils/portConflicts.ts). Не реактивна намеренно: это
// неизменяемый снимок, а не состояние формы.
let initialPortConfigs = new Map<string, PortConfig>()
// Подключения уже сохранённых портов на момент открытия формы (блок «Подключение» в строке порта): по
// снимку на сервер уходят только изменённые подключения (api/deviceInterfaces.ts:persistDeviceInterfaces).
// Тоже не реактивен намеренно. У нового устройства и у копии снимок пуст.
// shallowRef: baseline целиком заменяется при загрузке и передаётся редактору портов (освобождаемые порты).
const initialConnections = shallowRef<ConnectionBaseline>(new Map())
// Действующие подключения портов редактируемого устройства со сведениями о соседе — с сервера
// (GET /devices/{id}/interface-connections): по ним считаются расхождения конфигурации с соседними портами.
// Не зависит ни от общего списка подключений, ни от каталога интерфейсов (оба с потолком 1000 записей).
const savedConnections = shallowRef<DeviceInterfaceConnection[]>([])
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
// Пункт 3 правки "создание физического устройства": домен VLAN, заведённый вложенным "+" прямо
// здесь же (тем же путём domain_id -> nestedQuickAdd, что и pendingDomainMemberships выше) — это
// домен, который почти наверняка создан РАДИ синхронизации именно этого устройства, а не
// существовавший ранее домен, который здесь просто выбрали из списка (тот трогать нельзя — у
// него уже могут быть свои источник/участники/настройки). Поэтому здесь, в отличие от
// pendingDomainMemberships, id домена появляется ТОЛЬКО из события nested-created
// (DeviceVlanListEditor.vue:onNestedCreated), а не из самого факта членства.
const pendingSourceDomainIds = ref<Set<string>>(new Set())
const deviceTypeVlanIds = ref<Set<string>>(new Set())
const loadingNested = ref(false)

// Домены VLAN, в которых устройство состоит: сохранённое членство (memberDomainIds) плюс домены,
// добавленные в этой же сессии редактирования и ещё не сохранённые (pendingDomainMemberships,
// фикс п.1.3.8 — устройство уже "фактически" их участник для целей этой формы).
const deviceDomainIds = computed(() => new Set([...memberDomainIds.value, ...pendingDomainMemberships.value]))

// Правка "VLAN устройства" (пункт 3): если устройство состоит в домене VLAN, в списке выбора
// показываются ТОЛЬКО VLAN этого домена (доменов — если их несколько); если не состоит ни в одном —
// только VLAN без домена (доменные для не-участника бэкенд всё равно отклонил бы 422). Само правило
// вынесено в utils/vlan.ts:filterVlansForDeviceDomains — чистая функция, покрыта отдельными тестами.
const availableVlans = computed(() => filterVlansForDeviceDomains(vlansStore.allDefinitions, deviceDomainIds.value))

// Фикс п.2.2: единственный домен, к которому уже привязано устройство — только если он ровно
// один (см. комментарий к deviceDomainId в DeviceVlanListEditor.vue). Учитывает и
// pendingDomainMemberships через deviceDomainIds выше.
const singleDeviceDomainId = computed(() => (deviceDomainIds.value.size === 1 ? [...deviceDomainIds.value][0] : null))

// Пункты 1-2 правки "физическое устройство: расхождение с соседним портом": раньше здесь
// считалась только ГОТОВАЯ строка-предупреждение (interfaceConflictWarnings, Record<string,
// string>) для пассивной подсказки при наведении — саму информацию о соседнем порте и
// возможность применить любую из двух конфигураций пользователю было взять неоткуда. Теперь
// считается richer-объект (PortConflictInfo, см. api/types.ts) с фактическими значениями
// соседа — DeviceInterfacesEditor.vue сам решает, как их показать и что́ по каждой из двух
// кнопок применить (пункт 1 — is_management/is_data_transfer, пункт 2 — vlan_mode; это два
// НЕЗАВИСИМЫХ флага расхождения, у каждого своё место в интерфейсе редактора).
const interfaceConflicts = computed<Record<string, PortConflictInfo>>(() =>
  computePortConflicts(interfaces.value, savedConnections.value),
)

// Конфигурация соседних портов изменилась из этой формы («Применить текущую конфигурацию соседу», каскад режима
// порта): сведения о соседях перечитываются с сервера, чтобы значок расхождения исчез сразу. Ошибка не глотается —
// без обновления значок остался бы устаревшим.
async function reloadNeighborConfigs() {
  const deviceId = existingDeviceId.value
  if (!deviceId) return
  try {
    savedConnections.value = await fetchDeviceInterfaceConnections(deviceId)
  } catch (err) {
    notifyError(err)
  }
}

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
// Фикс п.2.1.2: симметричный случай — если VLAN устройства ДОБАВИЛСЯ (пользователь завёл новый
// VLAN в блоке "VLAN устройства"), порты, у которых уже были выбраны АБСОЛЮТНО ВСЕ старые опции
// ("Все VLAN" в DeviceInterfacesEditor.vue — не отдельный флаг, а именно это состояние, см. её
// isAllVlansSelected()), должны автоматически подхватить и новый VLAN тоже — иначе "Все VLAN"
// тут же перестаёт быть правдой при первом же добавлении нового VLAN на устройство, и
// пользователю пришлось бы вручную донастраивать уже отмеченный как "все" порт.
//
// КРИТИЧНО: сравниваем НОВЫЙ список опций со СТАРЫМ (аргумент oldOptions от Vue) и трогаем
// только vlan_ids, которые были разрешены раньше и перестали быть разрешены сейчас — а не
// просто "не входят в текущий portVlanOptions". Первое срабатывание случится сразу после
// начальной загрузки устройства (oldOptions на этот момент — пустой массив от самого первого
// вычисления computed, ещё до загрузки), и разница будет пустой — начальная загрузка порт не
// тронет. Если бы вместо диффа проверялось только текущее значение, при первой же загрузке
// стёрлись бы vlan_ids, назначенные через /legacy, но не входящие в этот более узкий каталог
// (тип устройства ∪ уже назначенные) — ровно такой баг поймал регрессионный тест в
// DeviceFormModal.spec.ts ("не стирает VLAN интерфейса, назначенные через /legacy..."). По той
// же причине пункт 2.1.2 применяется только когда oldOptions уже был непуст — на самой первой
// загрузке "все опции уже выбраны" было бы истинно вырожденно (для пустого множества) и
// разложило бы новые VLAN на все trunk-порты без разбора.
//
// Те же правила применяются и к ГРУППАМ портов (interfaceGroups): группа хранит свой vlan_ids, и
// сервер при сохранении записывает его во все порты группы — не обновлённая группа затёрла бы
// только что подхваченный портом новый VLAN (и оставила бы в группе снятый). Сама логика — в чистой
// функции reconcileVlanIds (utils/vlan.ts), общая для портов и групп.
watch(portVlanOptions, (options, oldOptions) => {
  const previous = oldOptions ?? []
  const rows = interfaces.value
  const nextRows = rows.map((row) => {
    const vlan_ids = reconcileVlanIds(row.vlan_ids, row.vlan_mode, previous, options)
    return vlan_ids === row.vlan_ids ? row : { ...row, vlan_ids }
  })
  if (nextRows.some((row, i) => row !== rows[i])) interfaces.value = nextRows

  // Подинтерфейсы, в отличие от VLAN порта и групп, молча не удаляются (на них IP-адреса и открытые порты): остаются на
  // снятом VLAN, подсвечиваются в редакторе портов и блокируют сохранение. Предупреждаем сразу, а не 422 при сохранении.
  const subinterfaceNotice = subinterfaceVlanRemovalMessage(nextRows, previous, options)
  if (subinterfaceNotice) notify(subinterfaceNotice, 'warning')

  const groups = interfaceGroups.value
  const nextGroups = groups.map((group) => {
    const vlan_ids = reconcileVlanIds(group.vlan_ids, group.vlan_mode, previous, options)
    return vlan_ids === group.vlan_ids ? group : { ...group, vlan_ids }
  })
  if (nextGroups.some((group, i) => group !== groups[i])) {
    interfaceGroups.value = nextGroups
    // Из групп VLAN убираются молча — предупреждаем: набор VLAN группы изменился не по действию пользователя в самой группе.
    const removalNotice = groupVlanRemovalMessage(groups, nextGroups, previous)
    if (removalNotice) notify(removalNotice, 'warning')
  }
})

// Набор VLAN устройства при открытии формы и в черновике: порядок строк не важен, пустые строки не считаются.
let initialDeviceVlanKey = ''
function deviceVlanKey(rows: DeviceVlanDraftRow[]): string {
  return rows
    .filter((row) => row.vlan_id)
    .map((row) => row.vlan_id)
    .sort()
    .join('|')
}

// После изменения списка VLAN устройства порты подхватывают их сами, а согласование с соседями идёт только вручную —
// подсказываем, если у подключений устройства теперь есть что согласовать. Не блокирует сохранение: ошибка проверки
// не отменяет уже сохранённое, о ней говорим отдельным предупреждением.
async function notifyAboutPortSync(deviceId: string): Promise<void> {
  try {
    const found = await findPortSyncNotice(deviceId)
    if (!found) return
    const scope = found.connectionIds.length > 0 ? { connection_ids: found.connectionIds } : {}
    notify(found.message, 'warning', {
      timeoutMs: 30000, // по уведомлению нужно решение — оно живёт дольше обычного предупреждения
      action: { label: 'Показать план', run: () => portSyncPlan.open(scope, 'Согласование портов после изменения VLAN устройства') },
    })
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err)
    notify(`Устройство сохранено, но проверить, нужно ли согласование портов, не удалось: ${reason}`, 'warning')
  }
}

function toSoftwareDraftRow(x: DeployedSoftware): SoftwareAssetDraftRow {
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

// Фикс п.2 (копирование сущностей): источник данных для формы — либо редактируемое устройство
// (props.device, обычный edit), либо "устройство-донор" для копирования (props.copyFrom). При
// копировании props.device остаётся null — это по-прежнему СОЗДАНИЕ нового устройства (submit()
// вызовет createResource, а не updateResource, см. existingDeviceId выше), просто форма стартует не с
// чистого листа, а с данными донора. View, открывающие форму, никогда не передают оба сразу.
const copySourceId = computed(() => props.device?.id ?? props.copyFrom?.id ?? null)

watch(
  copySourceId,
  async () => {
    // Аудит fix/usability-batch4 (находка №5): инвариант "device и copyFrom не передаются
    // одновременно" раньше был защищён только комментарием выше, не типами и не рантайм-
    // проверкой. Dev-warning — минимальная защита от неверного использования; device выигрывает
    // как более безопасный исход (обычный edit не даст случайно затереть данные копированием).
    if (props.device && props.copyFrom) {
      console.warn('DeviceFormModal: одновременно переданы device и copyFrom — используется device (режим редактирования)')
    }
    const source = props.device ?? props.copyFrom ?? null
    const isCopy = !props.device && !!props.copyFrom
    Object.assign(form, emptyForm())
    softwareAssets.value = []
    interfaces.value = []
    deviceVlans.value = []
    memberDomainIds.value = new Set()
    pendingDomainMemberships.value = new Set()
    pendingSourceDomainIds.value = new Set()
    deviceTypeVlanIds.value = new Set()
    initialPortConfigs = new Map()
    initialConnections.value = new Map()
    savedConnections.value = []
    if (source) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = source[key as keyof Device]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
      // serial_number уникален (UniqueConstraint в backend/app/models.py) — под тем же
      // серийником сохранить копию не получится, заставляем ввести новый явно.
      if (isCopy) form.serial_number = ''
    }
    // Пункт 3 правки "домен VLAN": справочник доменов для кнопки "Включить в домен" нужен и при
    // СОЗДАНИИ нового устройства (join-запрос откладывается в pendingDomainMemberships до
    // сохранения — тот же механизм, что уже есть для домена, заведённого через создание VLAN, см.
    // onVlanDomainCreated), поэтому загружается ДО ранней остановки ниже, а не внутри неё как
    // vlansStore (ему нужны данные конкретно существующего устройства).
    vlanDomainsStore.ensureLoaded()
    // Устройства-соседи и их свободные порты блок «Подключение» запрашивает у сервера сам (поиском со страницами),
    // полный список устройств форме не нужен.
    if (!source) return
    loadingNested.value = true
    try {
      const [software, ifaceRows, ifaceGroups, vlans, domainLinks, typeVlanIds, deviceConnections] = await Promise.all([
        listResource<DeployedSoftware>('deployed-software', { owner_type: 'physical_device', owner_id: source.id, limit: 1000 }),
        // Загрузка + сборка InterfaceDraftRow[] вынесена в api/deviceInterfaces.ts — тот же
        // помощник использует DevicePortsModal.vue (управление портами с экрана «Подключения»).
        // Открытые порты каждого интерфейса (фикс п.1.4, батч4) приходят уже вложенными в
        // ifaceRows[].open_ports — отдельно их грузить не нужно.
        loadDeviceInterfaceDraftRows(source.id),
        loadDeviceInterfaceGroups(source.id),
        listResource<DeviceVLAN>('device-vlans', { physical_device_id: source.id, limit: 1000 }),
        listResource<VLANDomainDeviceLink>('vlan-domain-devices', { physical_device_id: source.id, limit: 1000 }),
        // Загружается атомарно вместе с interfaces/deviceVlans (не через отдельный watch на
        // form.device_type_id — см. ниже) именно для того, чтобы portVlanOptions выше не
        // пересчитался с неполными данными между двумя разными по времени загрузками.
        loadDeviceTypeVlanIds(source.device_type_id),
        // Действующие подключения портов устройства — с сервера, а не из общего списка подключений (потолок 1000
        // записей): по ним строятся черновики подключений и снимок для отправки только изменённого. Копия
        // устройства подключений не наследует. Ошибка здесь не глотается: без них порт выглядел бы неподключённым.
        isCopy ? Promise.resolve([] as DeviceInterfaceConnection[]) : fetchDeviceInterfaceConnections(source.id),
        vlansStore.ensureLoaded(),
      ])
      // При копировании каждая вложенная строка должна создаться заново под НОВЫМ устройством, а
      // не обновить запись донора — id донора здесь означал бы именно "обновить эту же запись", и
      // backend/app/services/crud.py:sync_interfaces (для интерфейсов) или generic create/update
      // (для device-vlans/deployed-software — оба без выделенной sync-функции) отклонит его 422
      // "не принадлежит выбранному устройству", т.к. у нового устройства такого id ещё нет и
      // появиться неоткуда. stripIds() (см. ниже) убирает id из каждой строки — тогда backend
      // создаёт их как новые записи. Открытые порты каждого интерфейса — тот же принцип на один
      // уровень глубже (stripIds и на сам интерфейс, и на его open_ports, как уже делалось для
      // его ips).
      softwareAssets.value = isCopy ? stripIds(software.items.map(toSoftwareDraftRow)) : software.items.map(toSoftwareDraftRow)
      // Копия — новое устройство без подключений (connection: null); иначе у каждого порта подключается
      // его активное подключение (utils/interfaceConnections.ts).
      interfaces.value = isCopy
        ? ifaceRows.map((r) => ({ ...r, id: undefined, ips: stripIds(r.ips), open_ports: stripIds(r.open_ports), subinterfaces: stripSubinterfaceIds(r.subinterfaces), connection: null }))
        : attachConnectionDrafts(ifaceRows, deviceConnections)
      interfaceGroups.value = ifaceGroups
      // Копия: у нового устройства нет групп донора — группы создаются заново (без id, под новыми
      // ключами), а порты перевязываются на них.
      if (isCopy) {
        const cloned = cloneGroupsForCopy(ifaceGroups, interfaces.value)
        interfaceGroups.value = cloned.groups
        interfaces.value = cloned.rows
      }
      // При копировании id стёрты — снимок пуст, а у копии всё равно нет подключений и соседей.
      initialPortConfigs = snapshotPortConfigs(interfaces.value)
      initialConnections.value = snapshotConnections(interfaces.value)
      savedConnections.value = deviceConnections
      // Список VLAN устройства упорядочен по номеру VLAN (как открытые порты): vlansStore к этому моменту уже
      // загружен (ensureLoaded выше), так что номера известны.
      const vlanRows = vlans.items.map(toDeviceVlanDraftRow)
      deviceVlans.value = sortDeviceVlanRows(isCopy ? stripIds(vlanRows) : vlanRows, vlansStore.allDefinitions)
      initialDeviceVlanKey = deviceVlanKey(deviceVlans.value)
      // При копировании членство в доменах ещё не существует для НОВОГО устройства — переносим
      // как "предстоит создать при сохранении" (см. persistPendingDomainMemberships, фикс
      // п.1.3.8), а не как уже подтверждённое: иначе availableVlans выше решит, что устройство
      // уже участник домена, которым оно на самом деле пока не является, а связь так и не
      // создастся, поскольку persistPendingDomainMemberships читает только pendingDomainMemberships.
      if (isCopy) {
        pendingDomainMemberships.value = new Set(domainLinks.items.map((l) => l.domain_id))
      } else {
        memberDomainIds.value = new Set(domainLinks.items.map((l) => l.domain_id))
      }
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
// Пункт 2: поиск вводом текста в "Операционная система" и "Встроенная ОС" — тот же SearchableSelect,
// что у Здания/Помещения/Стойки выше. Подпись — catalogs.label() ("name version"), порядок — уже
// отсортированный catalogs.items (см. sortCatalogItems в stores/catalogs.ts).
const operatingSystemOptions = computed(() => (catalogs.items['operating-systems'] ?? []).map((os) => ({ value: os.id, label: catalogs.label('operating-systems', os.id) })))
const embeddedOsOptions = computed(() => (catalogs.items['embedded-os'] ?? []).map((os) => ({ value: os.id, label: catalogs.label('embedded-os', os.id) })))
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

// Поиск вводом текста в поле «Тип / производитель / модель» (SearchableSelect вместо нативного select).
// Порядок и группировка прежние: сначала модели по производителям (заведённые пользователем), в самом
// конце — «голые» типы без модели. Модель находится и по производителю с названием (они в подписи), и по
// названию её типа устройства (searchText — в списке не показывается), а запрос из нескольких слов
// требует каждое из них («коммутатор cisco»). Подпись выбранного — как раньше у option.
const TYPE_WITHOUT_MODEL_GROUP = 'Тип устройства (без конкретной модели)'
const typeModelOptions = computed<SearchableSelectOption[]>(() => {
  const models = modelGroups.value.flatMap((g) =>
    g.models.map((m) => ({
      value: `model:${m.id}`,
      label: modelOptionLabel(g, m),
      group: g.manufacturerName,
      searchText: catalogs.label('device-types', m.device_type_id, ''),
    })),
  )
  const types = (catalogs.items['device-types'] ?? []).map((t) => ({ value: `type:${t.id}`, label: t.name, group: TYPE_WITHOUT_MODEL_GROUP }))
  return [...models, ...types]
})

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

// Пункт 3 правки "создание физического устройства": в отличие от onVlanCreated выше (который
// реагирует на выбор ЛЮБОГО домена, включая уже существующий), это — событие именно СОЗДАНИЯ
// нового домена вложенным "+" (см. комментарий у pendingSourceDomainIds и цепочку nested-created
// в QuickAddModal.vue/QuickAddButton.vue/DeviceVlanListEditor.vue). Само присвоение
// source_device_id/auto_sync откладывается до persistPendingSourceDomains() ниже — у
// создаваемого устройства ещё может не быть id.
function onVlanDomainCreated(record: CatalogItem) {
  pendingSourceDomainIds.value = new Set([...pendingSourceDomainIds.value, record.id])
  // Новый домен ещё не в vlanDomainsStore — без перезагрузки его не было бы в списке memberDomains.
  vlanDomainsStore.reload()
}

// Пункт 3 правки "домен VLAN": кнопка "Включить в домен" в блоке "VLAN устройства"
// (DeviceVlanListEditor.vue) — прямой путь стать участником УЖЕ СУЩЕСТВУЮЩЕГО домена, в отличие
// от косвенного onVlanDomainCreated выше (который срабатывает только как побочный эффект
// заведения нового VLAN). Тот же pendingDomainMemberships и та же проверка "ещё не состоит" —
// см. onVlanCreated выше по файлу.
const joinableDomains = computed(() => vlanDomainsStore.all.filter((d) => !memberDomainIds.value.has(d.id) && !pendingDomainMemberships.value.has(d.id)))

// Пункты 3-4 правки "включение в домен VLAN": домены, в которых устройство состоит (или будет
// состоять после сохранения) — показываются в блоке "VLAN устройства", чтобы включение было видно
// сразу, а не только после перезагрузки страницы. Домены, которых ещё нет в vlanDomainsStore (например,
// только что созданный вложенным "+"), пропускаются — onVlanDomainCreated перезагружает стор, и они
// появятся сразу после его ответа.
const memberDomains = computed<DeviceMemberDomain[]>(() => {
  const nameById = new Map(vlanDomainsStore.all.map((d) => [d.id, d.name]))
  const result: DeviceMemberDomain[] = []
  for (const id of memberDomainIds.value) {
    if (nameById.has(id)) result.push({ id, name: nameById.get(id)!, pending: false })
  }
  for (const id of pendingDomainMemberships.value) {
    if (!memberDomainIds.value.has(id) && nameById.has(id)) result.push({ id, name: nameById.get(id)!, pending: true })
  }
  return result
})

async function onJoinDomainRequested(domainId: string) {
  if (memberDomainIds.value.has(domainId) || pendingDomainMemberships.value.has(domainId)) return
  pendingDomainMemberships.value = new Set([...pendingDomainMemberships.value, domainId])
  // Пункт 4: VLAN выбранного домена сразу попадают в черновик "VLAN устройства". Это не только
  // удобство: persistDeviceVlans() (PUT /devices/{id}/vlans) приводит VLAN устройства в БД ровно к
  // черновику — записи, которых в нём нет, удаляются. Поэтому VLAN, которые бэкенд сам назначит при
  // создании членства (services/crud.py:assign_domain_vlans_to_device), но которых нет в черновике,
  // были бы тут же убраны при этом же сохранении. Стор перезагружается (а не ensureLoaded), чтобы набор
  // VLAN домена был актуален на момент нажатия, а не на момент первой загрузки экрана.
  await vlansStore.reload()
  // Добавленные VLAN домена встают в общий список по номеру — как при добавлении строки вручную.
  const merged = mergeDomainVlansIntoDraft(deviceVlans.value, vlansStore.allDefinitions, domainId)
  deviceVlans.value = merged === deviceVlans.value ? merged : sortDeviceVlanRows(merged, vlansStore.allDefinitions)
}

// Отмена ещё не сохранённого включения в домен (кнопка × на pending-чипе в DeviceVlanListEditor):
// возвращает форму в состояние до «Включить» — домен снова предлагается в списке, а строки VLAN этого
// домена (и добавленные автоматически, и выбранные вручную после этого) убираются из черновика, иначе
// бэкенд отклонил бы их 422 (нет членства). Из pendingSourceDomainIds домен тоже исключается: если бы
// он остался, устройство всё равно стало бы источником домена (persistPendingSourceDomains), в который
// пользователь его включать передумал. Уже сохранённое членство (memberDomainIds) отменить нельзя.
function onCancelJoinDomain(domainId: string) {
  if (!pendingDomainMemberships.value.has(domainId)) return
  pendingDomainMemberships.value = new Set([...pendingDomainMemberships.value].filter((id) => id !== domainId))
  pendingSourceDomainIds.value = new Set([...pendingSourceDomainIds.value].filter((id) => id !== domainId))
  deviceVlans.value = removeDomainVlansFromDraft(deviceVlans.value, vlansStore.allDefinitions, domainId)
}

// Программные активы устройства — один атомарный PUT /devices/{id}/deployed-software (см.
// api/deviceDeployedSoftware.ts): сервер сравнивает список с БД по id, записи с id обновляются на
// месте, новые создаются, убранные в форме удаляются — без пересоздания всего ПО при каждом
// сохранении. Новому устройству (создание или копия) без заполненных строк синхронизировать нечего —
// запрос не отправляется; для существующего пустой список отправляется всегда, чтобы снять ПО,
// убранное пользователем. `deviceExisted` — устройство существовало до этого сохранения (редактирование
// или повтор после сбоя): для только что созданного пустой список синхронизировать не нужно.
async function persistSoftwareAssets(deviceId: string, deviceExisted: boolean) {
  if (!deviceExisted && !softwareAssets.value.some((row) => row.software_asset_id)) return
  await syncDeviceDeployedSoftware(deviceId, softwareAssets.value)
}

// Фикс п.1.3.8: закрепляет на бэкенде членство устройства в доменах, добавленных локально через
// onVlanCreated() выше (см. её комментарий и комментарий к pendingDomainMemberships). ДО
// persistDeviceVlans() ниже — _validate_physical_device_vlan в backend/app/services/crud.py
// проверяет членство устройства в домене VLAN при сохранении device-vlans и отклоняет запись
// с 422 "Устройство не включено в домен этого VLAN", если членства ещё нет.
// Уже созданные связи (joinedDomainIds) при повторе после сбоя пропускаются: POST — не идемпотентен.
async function persistPendingDomainMemberships(deviceId: string) {
  for (const domainId of pendingDomainMemberships.value) {
    if (joinedDomainIds.has(domainId)) continue
    await createResource('vlan-domain-devices', { physical_device_id: deviceId, domain_id: domainId })
    joinedDomainIds.add(domainId)
  }
}

// Пункт 3 правки "создание физического устройства": PUT (не POST) — домен уже существует
// (создан вложенным quick-add'ом на pendingSourceDomainIds.value.add в onVlanDomainCreated
// выше), здесь только доопределяем source_device_id/auto_sync частичным обновлением. Порядок
// относительно persistPendingDomainMemberships не важен — оба независимо пишут в vlan-domains
// разные записи/поля.
async function persistPendingSourceDomains(deviceId: string) {
  for (const domainId of pendingSourceDomainIds.value) {
    await updateResource('vlan-domains', domainId, { source_device_id: deviceId, auto_sync: true })
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
  const interfaceError =
    validateInterfaceDraftRows(interfaces.value, catalogs.protocolPortCatalog, new Set(portVlanOptions.value.map((v) => v.id))) ?? validateInterfaceGroups(interfaceGroups.value, catalogs.protocolPortCatalog) ?? validateConnectionDrafts(interfaces.value, initialConnections.value)
  if (interfaceError) {
    errorMessage.value = interfaceError
    return
  }
  // Фикс п.3 ("применить исправление [валидации IP] ко всем полям с ip"): "VLAN устройства"
  // (DeviceVlanListEditor.vue) — свой собственный IP/префикс на связи устройство-VLAN, отдельный
  // от IP на портах (interfaces.value.*.ips, уже проверены выше в validateInterfaceDraftRows).
  // Повторы VLAN — как повторы портов (бэкенд всё равно ответил бы 422): сообщаем сразу и раскрываем блок,
  // чтобы подсвеченные строки были видны, даже если список свёрнут по порогу.
  const duplicateVlans = duplicateVlansMessage(deviceVlans.value, vlansStore.allDefinitions)
  if (duplicateVlans) {
    errorMessage.value = duplicateVlans
    vlanEditor.value?.expand()
    return
  }
  for (const row of deviceVlans.value) {
    if (!isValidIPv4(row.ip_address)) {
      errorMessage.value = `Некорректный IP-адрес «${row.ip_address}» в блоке "VLAN устройства".`
      vlanEditor.value?.expand()
      return
    }
    if (!isValidPrefixLength(row.prefix_length)) {
      errorMessage.value = `Некорректный префикс «${row.prefix_length}» в блоке "VLAN устройства" — допустимо 0-32.`
      vlanEditor.value?.expand()
      return
    }
  }

  saving.value = true
  // Расхождение назначения/режима порта с соседом, появившееся в этом сохранении, показываем ДО записи — диалогом с
  // возможностью применить конфигурацию соседа или текущего порта, а не только уведомлением после неё (когда форма
  // уже закрыта). Редактор портов не смонтирован (ещё грузится) — проверять нечего.
  if (interfacesEditor.value && !(await interfacesEditor.value.reviewNeighborMismatches(initialPortConfigs))) {
    saving.value = false
    return
  }
  // Меняются ли подключения портов в этом сохранении (и у каких уже сохранённых портов) — от этого
  // зависит, нужно ли после сохранения обновлять стор подключений (см. ниже).
  const connectionsChanged = hasConnectionChanges(interfaces.value, initialConnections.value)
  const changedConnectionIds = changedConnectionRowIds(interfaces.value, initialConnections.value)
  // Устройство создано именно этим сохранением (а не раньше) — нужно, чтобы при сбое следующих шагов
  // честно сказать об этом пользователю (см. catch ниже).
  let createdByThisSubmit = false
  try {
    let extra: Record<string, unknown> | undefined
    // До трёх попыток: обычная отправка, затем до двух ре-отправок с флагами
    // подтверждения, если пользователь согласился на диалоге.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const payload = toPayload(extra)
        // Устройство уже есть — редактирование либо повтор после сбоя (см. createdDevice): обновляем его.
        const deviceId = existingDeviceId.value
        const saved = deviceId ? await updateResource<Device>('devices', deviceId, payload) : await createResource<Device>('devices', payload)
        if (!deviceId) {
          createdDevice.value = saved
          createdByThisSubmit = true
        }
        await persistSoftwareAssets(saved.id, deviceId !== null)
        await persistPendingDomainMemberships(saved.id)
        await persistPendingSourceDomains(saved.id)
        // persistDeviceVlans ДО persistDeviceInterfaces (не как раньше) — sync_interfaces на
        // бэкенде проверяет vlan_ids порта против уже сохранённых в БД PhysicalDeviceVLAN (см.
        // allowed_vlans в backend/app/services/crud.py). Если VLAN только что добавлен в блок
        // "VLAN устройства" и тут же назначен порту в этом же сохранении, к моменту проверки он
        // должен уже быть в БД — иначе 422 "VLAN не разрешён" на ровном месте для пользователя.
        const deviceVlansChanged = !!props.device && deviceVlanKey(deviceVlans.value) !== initialDeviceVlanKey
        await persistDeviceVlans(saved.id, deviceVlans.value)
        // Атомарный PUT (не через generic createResource/deleteResource) — см.
        // api/deviceInterfaces.ts:persistDeviceInterfaces.
        const { items: savedInterfaces } = await persistDeviceInterfaces(saved.id, interfaces.value, interfaceGroups.value, initialConnections.value)
        // Фикс п.3.1: без этого catalogs.items['interfaces'] не узнаёт о только что
        // сохранённых портах устройства (persistDeviceInterfaces — чистый API-вызов, сам кэш
        // каталогов не трогает по дизайну, см. её комментарий), и поле "Порт" в форме
        // подключения (ConnectionFormModal.vue, читает ровно этот кэш) оставалось пустым для
        // нового устройства до жёсткой перезагрузки страницы, обнуляющей кэш и вызывающей
        // catalogs.reload() заново. DevicePortsModal.vue делает этот же вызов уже сейчас —
        // здесь его просто не было для основного пути создания/редактирования устройства.
        catalogs.replaceDeviceInterfaces(saved.id, savedInterfaces)
        // Пункт 3: сторы VLAN и доменов читаются другими экранами (VLANsView, DevicesView) без
        // повторной загрузки — без этого включение в домен и новые VLAN устройства были видны там
        // только после перезагрузки страницы. reload() сам не бросает (ошибка пишется в store.error).
        await Promise.all([vlansStore.reload(), pendingDomainMemberships.value.size || pendingSourceDomainIds.value.size ? vlanDomainsStore.reload() : Promise.resolve()])
        // Пункт 5: interfaceConflicts считается по черновику interfaces — то есть ровно по тому, что
        // только что сохранено.
        // Подключения портов созданы/изменены этим же сохранением: стор подключений устарел, а у новых портов
        // только сейчас появились id — сверяем с соседями уже сохранённые порты (ответ сервера), а не
        // черновые строки. Без изменений подключений — прежний путь (стор не перезагружаем).
        let noticeRows: PortRowLike[] = interfaces.value
        let noticeConflicts = interfaceConflicts.value
        if (connectionsChanged) {
          // Соседи берутся у сервера для этого устройства, а не из общего списка подключений. Общий список
          // (его читают экраны «Подключения» и схема) обновляем, только если он уже загружен: иначе он и так
          // загрузится свежим при первом обращении.
          savedConnections.value = await fetchDeviceInterfaceConnections(saved.id)
          if (connectionsStore.loaded) await connectionsStore.reload()
          noticeRows = savedInterfaces
          noticeConflicts = computePortConflicts(noticeRows, savedConnections.value)
        }
        const conflictNotice = buildPortConflictNotice(noticeRows, noticeConflicts, initialPortConfigs, changedConnectionIds)
        if (conflictNotice) notify(conflictNotice, 'warning')
        emit('saved', saved)
        // Проверка идёт уже после закрытия формы и не задерживает его; сама ловит свои ошибки.
        if (deviceVlansChanged) void notifyAboutPortSync(saved.id)
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
    const reason = err instanceof Error ? err.message : 'Не удалось сохранить устройство'
    if (createdByThisSubmit) {
      // Устройство уже в БД, а остальное не сохранилось: говорим об этом прямо и обновляем список —
      // родитель перезагружает его только по 'saved', а форма остаётся открытой для исправления.
      errorMessage.value = `Устройство создано, но остальные данные сохранить не удалось: ${reason.replace(/[\s.]+$/, '')}. Исправьте данные и нажмите «Сохранить» ещё раз — устройство будет обновлено, а не создано повторно.`
      await devicesStore.reload()
    } else {
      errorMessage.value = reason
    }
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
            <SearchableSelect v-model="typeModelSelection" :options="typeModelOptions" placeholder="— выберите —" />
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
            <SearchableSelect v-model="form.operating_system_id" :options="operatingSystemOptions" placeholder="— не указана —" />
            <QuickAddButton resource="operating-systems" title="Операционная система" @created="(r) => (form.operating_system_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Встроенная ОС (для сетевого оборудования)</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.embedded_os_id" :options="embeddedOsOptions" placeholder="— не указана —" />
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

        <div class="field field-wide oac-cert-block">
          <div class="oac-cert-head">
            <b>Сертификат ОАЦ</b>
            <span class="hint">Необязательно — заполняется, если на устройстве установлено сертифицированное средство криптографической защиты информации.</span>
          </div>
          <div class="oac-cert-grid">
            <label class="field">
              <span>Регистрационный номер сертификата соответствия (экспертного заключения)</span>
              <input
                v-model.trim="form.oac_certificate_number"
                v-truncate-tooltip="form.oac_certificate_number"
                type="text"
                maxlength="255"
              />
            </label>
            <label class="field">
              <span>Дата внесения в реестр</span>
              <input v-model="form.oac_certificate_registry_date" type="date" />
            </label>
          </div>
        </div>

        <div class="field field-wide">
          <DeviceIconPicker :model-value="form.diagram_icon_id || null" @update:model-value="form.diagram_icon_id = $event ?? ''" />
        </div>

        <p v-if="loadingNested" class="loading-hint field-wide">Загрузка портов, ПО, интерфейсов и VLAN…</p>
        <SoftwareAssetListEditor v-if="!loadingNested" v-model="softwareAssets" :catalog-entries="catalogs.items['software-assets'] ?? []" />
        <DeviceInterfacesEditor
          v-if="!loadingNested"
          ref="interfacesEditor"
          v-model="interfaces"
          v-model:groups="interfaceGroups"
          :type-options="catalogs.items['interface-types'] ?? []"
          :speed-options="catalogs.items['interface-speeds'] ?? []"
          :vlan-options="portVlanOptions"
          :conflicts="interfaceConflicts"
          :protocol-port-catalog="catalogs.protocolPortCatalog"
          :device-id="props.device?.id ?? null"
          :device-label="form.system_name || form.serial_number"
          edit-connections
          :connection-baseline="initialConnections"
          @neighbors-changed="reloadNeighborConfigs"
        />
        <DeviceVlanListEditor
          v-if="!loadingNested"
          ref="vlanEditor"
          v-model="deviceVlans"
          :collapse-after="formPreferences.deviceVlanCollapseRows"
          :vlan-options="availableVlans"
          :all-vlan-definitions="vlansStore.allDefinitions"
          :device-domain-id="singleDeviceDomainId"
          :joinable-domains="joinableDomains"
          :member-domains="memberDomains"
          @cancel-join-domain="onCancelJoinDomain"
          @vlan-created="onVlanCreated"
          @vlan-domain-created="onVlanDomainCreated"
          @join-domain="onJoinDomainRequested"
        />
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
  /* Список интерфейсов (DeviceInterfacesEditor.vue) — таблица из 10 колонок; на типичных
     (не сверхширoких) десктопных окнах 50vw заметно уже, чем ей нужно, и до кнопок удаления и
     "Применить к выбранным" в последней колонке приходится прокручивать таблицу горизонтально.
     Увеличенные 70vw/1400px дают заметно больше места именно на таких окнах (напр. 1440px
     окно: было 720px, стало ~1008px), а нижняя граница 640px не меняется — на узких экранах
     ничего не задевает, и там же по-прежнему работает .iface-table-wrap { overflow-x: auto }
     как запасной вариант. */
  max-width: clamp(640px, 70vw, 1400px);
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
.oac-cert-block {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  gap: 10px;
}
.oac-cert-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.oac-cert-head b {
  font-size: 12.5px;
  color: var(--ink);
}
.oac-cert-head .hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.oac-cert-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
@media (max-width: 640px) {
  .oac-cert-grid {
    grid-template-columns: 1fr;
  }
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.lookup-row select,
.lookup-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.field input[type='text'],
.field input[type='date'],
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
/* Фикс: "Дата внесения в реестр" (единственный input[type=date] в этой форме) визуально
   выпадала из стиля проекта — селектор выше раньше подхватывал только input[type='text'], а
   тёмная тема приложения (theme.css) нигде не объявляет color-scheme, поэтому нативные иконка
   календаря и всплывающий пикер браузера всегда светлые поверх тёмного инпута. color-scheme
   переключает именно их палитру на тёмную, ничего в разметке/поведении не меняя; ширина/фон/
   рамка самого поля уже выровнены общим правилом выше. Область действия — только это поле, а
   не вся тема, т.к. остальные нативные контролы приложения (например, <select>) решены иначе —
   собственным SearchableSelect.vue, а не color-scheme. */
.oac-cert-grid input[type='date'] {
  color-scheme: dark;
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
