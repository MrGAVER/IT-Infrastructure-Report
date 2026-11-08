// Черновик формы устройства (DeviceFormModal.vue): всё, что пользователь правит в форме, и то, что форма запоминает о
// сохранённом состоянии. Только состояние — загрузка, сохранение и правила (домены, VLAN портов) работают поверх него:
// useDeviceLoader, useDeviceSave, useDeviceDomains, useDevicePortVlans, useDeviceStackVlans.
import { computed, reactive, ref, shallowRef } from 'vue'
import type { DeviceInterfaceConnection } from '../api/deviceConnectivity'
import type { Device, DeviceVlanDraftRow, InterfaceDraftRow, InterfaceGroupDraft, SoftwareAssetDraftRow, PortConflictInfo } from '../api/types'
import { emptyDeviceForm } from '../utils/deviceForm'
import { computePortConflicts, type PortConfig } from '../utils/portConflicts'
import type { ConnectionBaseline } from '../utils/interfaceConnections'

export function useDeviceDraft(device: () => Device | null) {
  const errorMessage = ref<string | null>(null)
  // Устройство, которое ЭТА форма уже создала, но не смогла сохранить целиком: после createResource идёт
  // несколько отдельных запросов (ПО, домены, VLAN, порты и подключения), и сбой любого из них оставляет
  // устройство в БД. Пока оно задано, повторное «Сохранить» ОБНОВЛЯЕТ его — иначе второй POST создал бы дубль,
  // а пользователь не смог бы исправить данные и дозаписать.
  const createdDevice = ref<Device | null>(null)
  // Домены, в которые устройство уже включено запросом этой формы: повтор после сбоя не должен отправлять
  // POST vlan-domain-devices второй раз (связь уже создана).
  const joinedDomainIds = new Set<string>()
  const existingDeviceId = computed(() => device()?.id ?? createdDevice.value?.id ?? null)
  const isEdit = computed(() => existingDeviceId.value !== null)

  const form = reactive(emptyDeviceForm())

  // Фикс п.1.4 (батч4): открытые порты больше не самостоятельный список уровня устройства — теперь
  // это InterfaceDraftRow.open_ports внутри каждой строки interfaces (см. её комментарий в
  // api/types/interfaces.ts) и персистятся атомарно вместе с интерфейсом через persistDeviceInterfaces().
  const softwareAssets = ref<SoftwareAssetDraftRow[]>([])
  const interfaces = ref<InterfaceDraftRow[]>([])
  // Группы портов (InterfaceGroupsPanel.vue внутри DeviceInterfacesEditor.vue): общие режим порта/VLAN,
  // IP и открытые порты для нескольких портов. Грузятся с портами и сохраняются с ними одним PUT.
  const interfaceGroups = ref<InterfaceGroupDraft[]>([])
  const deviceVlans = ref<DeviceVlanDraftRow[]>([])

  // Домены VLAN: сохранённое членство, членство, которое предстоит создать при сохранении формы (staged-черновик, как у
  // interfaces/deviceVlans), и домены, заведённые вложенным «+» ради синхронизации именно этого устройства (см. useDeviceDomains.ts).
  const memberDomainIds = ref<Set<string>>(new Set())
  const pendingDomainMemberships = ref<Set<string>>(new Set())
  const pendingSourceDomainIds = ref<Set<string>>(new Set())
  const deviceTypeVlanIds = ref<Set<string>>(new Set())
  const loadingNested = ref(false)

  // Пункт 5: конфигурация (Управление/Передача данных/режим порта) уже сохранённых портов на момент
  // открытия формы — по ней при сохранении определяется, что конфигурация порта с расхождением
  // относительно соседа сохраняется ВПЕРВЫЕ (см. utils/portConflicts.ts). Не реактивна намеренно: это
  // неизменяемый снимок, а не состояние формы. Так же устроен ключ набора VLAN устройства на момент открытия формы.
  const snapshot = { portConfigs: new Map<string, PortConfig>(), deviceVlanKey: '' }
  // Подключения уже сохранённых портов на момент открытия формы (блок «Подключение» в строке порта): по
  // снимку на сервер уходят только изменённые подключения (api/deviceInterfaces.ts:persistDeviceInterfaces).
  // Тоже не реактивен намеренно. У нового устройства и у копии снимок пуст.
  // shallowRef: baseline целиком заменяется при загрузке и передаётся редактору портов (освобождаемые порты).
  const initialConnections = shallowRef<ConnectionBaseline>(new Map())
  // Действующие подключения портов редактируемого устройства со сведениями о соседе — с сервера
  // (GET /devices/{id}/interface-connections): по ним считаются расхождения конфигурации с соседними портами.
  // Не зависит ни от общего списка подключений, ни от каталога интерфейсов (оба с потолком 1000 записей).
  const savedConnections = shallowRef<DeviceInterfaceConnection[]>([])

  // Расхождения конфигурации портов с соседними (PortConflictInfo, см. api/types) — с фактическими значениями соседа:
  // DeviceInterfacesEditor.vue сам решает, как их показать и что применить по каждой из двух кнопок.
  const interfaceConflicts = computed<Record<string, PortConflictInfo>>(() => computePortConflicts(interfaces.value, savedConnections.value))

  /** Форма заново открыта для другого источника: черновик возвращается в пустое состояние (группы портов не трогаются —
   * их заменяет загрузка источника). */
  function reset() {
    Object.assign(form, emptyDeviceForm())
    softwareAssets.value = []
    interfaces.value = []
    deviceVlans.value = []
    memberDomainIds.value = new Set()
    pendingDomainMemberships.value = new Set()
    pendingSourceDomainIds.value = new Set()
    deviceTypeVlanIds.value = new Set()
    snapshot.portConfigs = new Map()
    initialConnections.value = new Map()
    savedConnections.value = []
  }

  return {
    errorMessage,
    createdDevice,
    joinedDomainIds,
    existingDeviceId,
    isEdit,
    form,
    softwareAssets,
    interfaces,
    interfaceGroups,
    deviceVlans,
    memberDomainIds,
    pendingDomainMemberships,
    pendingSourceDomainIds,
    deviceTypeVlanIds,
    loadingNested,
    snapshot,
    initialConnections,
    savedConnections,
    interfaceConflicts,
    reset,
  }
}

export type DeviceDraft = ReturnType<typeof useDeviceDraft>
