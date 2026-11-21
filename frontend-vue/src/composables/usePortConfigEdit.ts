// Состояние и запись правки одного порта (окно PortConfigEditModal): загрузка текущей конфигурации с сервера, черновик (роль, режим,
// VLAN), копирование с соседнего порта и сохранение — обычным запросом или каскадом смены режима. Вынесено из PortConfigEditModal.vue без
// изменения поведения; окно осталось отвечать за разметку. Описание того, как именно записывается правка, — в комментарии самого окна.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { loadDeviceInterfaceGroups } from '../api/deviceInterfaces'
import { setPortConfig } from '../api/portConfig'
import { computePortVlanOptions, loadAssignedDeviceVlanIds, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Connection, Device, DeviceInterface, InterfaceGroupDraft, InterfaceVlansEntry, VLANDefinition, VlanMode } from '../api/types'
import type { CascadePortRequest } from '../api/vlanModeCascade'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useVLANsStore } from '../stores/vlans'
import { formatVlans, portRoleOf } from '../utils/portConfig'
import {
  adaptVlanIdsToMode,
  buildPortConfigPatch,
  cloneDraft,
  differencesFromNeighbor,
  isDirty,
  numbersOf,
  validateDraft,
  vlanIdsForNumbers,
  type PortDraft,
} from '../utils/portEdit'
import { useToast } from './useToast'
import { useVlanModeCascade, type CascadeOutcome } from './useVlanModeCascade'

/** Какой порт подключения правим: `side` — его сторона, вторая сторона — «сосед» (для сравнения). */
export interface PortConfigEditProps {
  readonly connection: Connection
  readonly side: 'source' | 'destination'
}

/** Что окну нужно знать о завершении: правка сохранена (таблица уже перечитана) или окно можно закрыть. */
export interface PortConfigEditEvents {
  saved: () => void
  close: () => void
}

export function usePortConfigEdit(props: PortConfigEditProps, events: PortConfigEditEvents) {
  const catalogs = useCatalogsStore()
  const vlansStore = useVLANsStore()
  const dashboard = useConnectionsDashboardStore()
  const { notify } = useToast()

  const own = computed(() => {
    const c = props.connection
    return props.side === 'source'
      ? { interfaceId: c.source_interface_id, name: c.source_interface_name, deviceLabel: c.source_device_name }
      : { interfaceId: c.destination_interface_id, name: c.destination_interface_name, deviceLabel: c.destination_device_name }
  })
  // Сосед — только для сравнения: его конфигурация здесь не меняется.
  const neighbor = computed(() => {
    const c = props.connection
    return props.side === 'source'
      ? {
          name: c.destination_interface_name,
          deviceLabel: c.destination_device_name,
          role: c.destination_port_role,
          mode: c.destination_vlan_mode,
          vlans: c.destination_vlans,
        }
      : { name: c.source_interface_name, deviceLabel: c.source_device_name, role: c.source_port_role, mode: c.source_vlan_mode, vlans: c.source_vlans }
  })

  const loading = ref(true)
  const saving = ref(false)
  const errorMessage = ref<string | null>(null)
  const notice = ref<string | null>(null)

  const vlanOptions = ref<VLANDefinition[]>([])
  const group = ref<InterfaceGroupDraft | null>(null)
  const initial = ref<PortDraft>({ role: 'none', mode: 'trunk', vlanIds: [], allVlans: false })
  const draft = reactive<PortDraft>({ role: 'none', mode: 'trunk', vlanIds: [], allVlans: false })

  // Группа, задающая режим и VLAN порта, — источник истины: набор VLAN порта здесь не правится.
  const vlansLocked = computed(() => Boolean(group.value?.vlan_mode))
  const modeChanged = computed(() => draft.mode !== initial.value.mode)
  const dirty = computed(() => isDirty(initial.value, draft))
  const draftVlanNumbers = computed(() => numbersOf(vlanOptions.value, draft.vlanIds))
  const differences = computed(() => differencesFromNeighbor(draft, draftVlanNumbers.value, neighbor.value))

  function setDraft(next: PortDraft) {
    draft.role = next.role
    draft.mode = next.mode
    draft.vlanIds = [...next.vlanIds]
    draft.allVlans = next.allVlans
  }

  /** Текущее состояние порта с сервера: роль, режим, VLAN и группа — не из строки таблицы, которая могла устареть. */
  async function loadPort() {
    const id = own.value.interfaceId
    const iface = await api.get<DeviceInterface>(`/resources/interfaces/${id}`)
    // VLAN порта — запросом устройства: он учитывает признак «Все VLAN» (у такого порта связей в БД нет, набор — все VLAN
    // устройства), которого generic-список связей не знает.
    const [device, portVlans, groups] = await Promise.all([
      api.get<Device>(`/resources/devices/${iface.physical_device_id}`),
      api.get<{ items: InterfaceVlansEntry[] }>(`/devices/${iface.physical_device_id}/interface-vlans`),
      iface.group_id ? loadDeviceInterfaceGroups(iface.physical_device_id) : Promise.resolve([] as InterfaceGroupDraft[]),
    ])
    const [typeVlanIds, assignedVlanIds] = await Promise.all([
      loadDeviceTypeVlanIds(device.device_type_id),
      loadAssignedDeviceVlanIds(iface.physical_device_id),
    ])
    vlanOptions.value = computePortVlanOptions(vlansStore.allDefinitions, typeVlanIds, assignedVlanIds)
    group.value = groups.find((g) => g.id === iface.group_id) ?? null
    const portEntry = portVlans.items.find((item) => item.interface_id === id)
    const mode = (iface.vlan_mode as VlanMode) || 'trunk'
    initial.value = {
      role: portRoleOf(iface),
      mode,
      vlanIds: [...new Set(portEntry?.vlan_ids ?? [])],
      allVlans: mode === 'trunk' && portEntry?.all_vlans === true,
    }
    setDraft(initial.value)
  }

  onMounted(async () => {
    try {
      await Promise.all([catalogs.ensureLoaded(), vlansStore.ensureLoaded()])
      await loadPort()
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить настройки порта'
    } finally {
      loading.value = false
    }
  })

  // В access остаётся один VLAN с наименьшим номером — как в форме устройства и в каскаде; у порта в группе
  // набор не трогаем: его определит каскад по группе.
  watch(
    () => draft.mode,
    (mode) => {
      if (loading.value || vlansLocked.value) return
      if (mode === 'access') draft.allVlans = false // «Все VLAN» только в trunk
      const adapted = adaptVlanIdsToMode(vlanOptions.value, draft.vlanIds, mode)
      if (adapted.length !== draft.vlanIds.length) {
        notice.value = 'В режиме access у порта один VLAN — оставлен VLAN с наименьшим номером.'
        draft.vlanIds = adapted
      }
    },
  )

  function toggleVlan(id: string, checked: boolean) {
    notice.value = null
    if (draft.mode === 'access') draft.vlanIds = checked ? [id] : []
    else draft.vlanIds = checked ? [...new Set([...draft.vlanIds, id])] : draft.vlanIds.filter((v) => v !== id)
    draft.allVlans = false // ручной выбор снимает «Все VLAN», даже если выбраны все
  }

  function selectAllVlans() {
    notice.value = null
    draft.vlanIds = vlanOptions.value.map((o) => o.id)
    draft.allVlans = true // сохраняемый признак, а не просто полный набор
  }

  function clearVlans() {
    notice.value = null
    draft.vlanIds = []
    draft.allVlans = false
  }

  /** Роль, режим и VLAN как у порта на другом конце подключения. VLAN сопоставляются по НОМЕРУ — как и при
   * сверке; номера, которых нет у устройства порта, не назначаются. */
  function copyFromNeighbor() {
    const n = neighbor.value
    notice.value = null
    if (n.role) draft.role = n.role
    if (n.mode) draft.mode = n.mode
    if (!vlansLocked.value) {
      const { ids, missing } = vlanIdsForNumbers(vlanOptions.value, n.vlans)
      draft.vlanIds = adaptVlanIdsToMode(vlanOptions.value, ids, draft.mode)
      draft.allVlans = false // набор сопоставлен по номерам — это выбор вручную, не «Все VLAN»
      if (missing.length) notice.value = `У устройства порта нет VLAN ${formatVlans(missing)} — они не назначены.`
    }
  }

  // --- запись ------------------------------------------------------------------------------------

  /** Роль и набор VLAN обычным запросом (режим не менялся, либо уже был целевым). Ошибку не пробрасывает, а показывает
   * в окне и перечитывает состояние порта — введённое пользователем не теряется, можно повторить. `resendVlans` —
   * набор отправляется целиком, даже если он совпал с исходным (режим порта менялся другим способом). */
  async function applyRoleAndVlans(resendVlans: boolean) {
    const patch = buildPortConfigPatch(initial.value, draft, { modeChanged: resendVlans, vlansLocked: vlansLocked.value })
    try {
      if (patch) {
        catalogs.replaceInterface(await setPortConfig(own.value.interfaceId, patch))
        notify('Конфигурация порта обновлена', 'success')
      } else if (!resendVlans) {
        notify('Изменений нет', 'info')
      }
      await dashboard.refreshAfterChange()
      events.saved()
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить роль и VLAN порта'
      await refreshAfterFailure()
    }
  }

  /** Роль и VLAN для записи вместе с каскадом: то же, что `buildPortConfigPatch`, без режима (его задаёт каскад). */
  function cascadePortRequest(): CascadePortRequest | null {
    const patch = buildPortConfigPatch(initial.value, draft, { modeChanged: true, vlansLocked: vlansLocked.value })
    if (!patch) return null
    const request: CascadePortRequest = {}
    if (patch.role !== undefined) request.role = patch.role
    if (patch.vlan_ids !== undefined) request.vlan_ids = patch.vlan_ids
    if (patch.all_vlans !== undefined) request.all_vlans = patch.all_vlans
    return request
  }

  async function refreshAfterFailure() {
    try {
      const wanted = cloneDraft(draft)
      await loadPort()
      setDraft(wanted) // введённое пользователем не теряем — сверка с исходным пересчитается с новым состоянием порта
      await dashboard.refreshAfterChange()
    } catch {
      /* состояние порта не обновилось — ошибка выше уже показана, окно остаётся как есть */
    }
  }

  let cascadePort: CascadePortRequest | null = null
  const {
    pending: cascadePending,
    applying: cascadeApplying,
    start: cascadeStart,
    confirm: cascadeConfirm,
    cancel: cascadeCancel,
  } = useVlanModeCascade({
    edited: () => null,
    port: () => cascadePort,
    async onFinished(outcome: CascadeOutcome) {
      if (outcome === 'unchanged') {
        // Режим уже целевой — каскад ничего не применял, роль и VLAN идут обычной правкой.
        await applyRoleAndVlans(true)
        return
      }
      // Режим, роль и VLAN записаны одной транзакцией каскада.
      if (cascadePort) notify('Конфигурация порта обновлена', 'success')
      await dashboard.refreshAfterChange()
      events.saved()
    },
  })

  async function save() {
    errorMessage.value = validateDraft(draft, { vlansLocked: vlansLocked.value })
    if (errorMessage.value) return
    if (!dirty.value) {
      events.close()
      return
    }
    saving.value = true
    try {
      if (modeChanged.value) {
        // Предпросмотр (вместе с проверкой роли и VLAN) и подтверждение — в окне каскада; запись — одним запросом.
        cascadePort = cascadePortRequest()
        await cascadeStart(own.value.interfaceId, draft.mode, `«${own.value.name}» (${own.value.deviceLabel})`)
      } else {
        await applyRoleAndVlans(false)
      }
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить настройки порта'
    } finally {
      saving.value = false
    }
  }

  return {
    own,
    neighbor,
    loading,
    saving,
    errorMessage,
    notice,
    vlanOptions,
    group,
    draft,
    vlansLocked,
    modeChanged,
    dirty,
    differences,
    toggleVlan,
    selectAllVlans,
    clearVlans,
    copyFromNeighbor,
    save,
    cascadePending,
    cascadeApplying,
    cascadeConfirm,
    cascadeCancel,
  }
}
