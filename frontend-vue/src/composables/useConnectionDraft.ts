// Состояние формы подключения (ConnectionFormModal.vue): форма, выбор устройств и портов (устройство → порт) и их опции.
//
// Источник и назначение выбираются в два шага, т.к. интерфейсы принадлежат конкретному устройству. Список портов на каждом шаге
// исключает уже занятые активным подключением (connections store: occupiedInterfaceIds) — сервер всё равно отклонил бы конфликт
// с 409 (validate_connection в backend/app/services/validation.py), но лучше не доводить до этой ошибки. При редактировании
// собственные текущие порты подключения не считаются занятыми — иначе нельзя было бы просто поменять, например, тип линии.
import { computed, reactive, ref, watch } from 'vue'
import type { Connection, DeviceInterface } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsStore } from '../stores/connections'
import { useDevicesStore } from '../stores/devices'
import { connectionDeviceLabel, connectionFormFromSource, countDeviceInterfaces, emptyConnectionForm, freeInterfacesForDevice, type ConnectionPrefill } from '../utils/connectionForm'
import { sortOptionsByLabel } from '../utils/selectOptions'

export interface ConnectionDraftSource {
  /** Редактируемое подключение (null — создание). */
  connection: () => Connection | null
  /** Подсказка схемы для создания; при редактировании игнорируется. */
  prefill: () => ConnectionPrefill | null | undefined
}

export type ConnectionEndpoint = 'source' | 'destination'

export function useConnectionDraft(source: ConnectionDraftSource) {
  const catalogs = useCatalogsStore()
  const devicesStore = useDevicesStore()
  const connectionsStore = useConnectionsStore()

  const saving = ref(false)
  const errorMessage = ref<string | null>(null)
  // true — показан выбор решения по расхождению вместо кнопок «Отмена/Сохранить».
  const resolving = ref(false)
  const isEdit = computed(() => source.connection() !== null)
  const form = reactive(emptyConnectionForm())

  const allInterfaces = computed(() => (catalogs.items['interfaces'] ?? []) as unknown as DeviceInterface[])
  const selectedSourceInterface = computed(() => allInterfaces.value.find((i) => i.id === form.source_interface_id) ?? null)
  const selectedDestinationInterface = computed(() => allInterfaces.value.find((i) => i.id === form.destination_interface_id) ?? null)

  const sourceInterfaces = computed(() => freeInterfacesForDevice(allInterfaces.value, connectionsStore.occupiedInterfaceIds, form.sourceDeviceId, form.source_interface_id))
  const destinationInterfaces = computed(() => freeInterfacesForDevice(allInterfaces.value, connectionsStore.occupiedInterfaceIds, form.destinationDeviceId, form.destination_interface_id))

  // Поиск вводом текста в «Устройство»/«Порт». deviceOptions сортируется здесь же (в devicesStore.all порядок — как пришло с
  // бэкенда, серверной сортировки нет); порты приходят уже отсортированными natural sort'ом (stores/catalogs.ts), .filter() порядок
  // не меняет.
  const deviceOptions = computed(() => sortOptionsByLabel(devicesStore.all.map((d) => ({ value: d.id, label: connectionDeviceLabel(d) }))))
  const sourcePortOptions = computed(() => sourceInterfaces.value.map((i) => ({ value: i.id, label: i.name })))
  const destinationPortOptions = computed(() => destinationInterfaces.value.map((i) => ({ value: i.id, label: i.name })))
  const connectionTypeOptions = computed(() => (catalogs.items['connection-types'] ?? []).map((t) => ({ value: t.id, label: t.name })))
  const sourceHasNoInterfacesAtAll = computed(() => form.sourceDeviceId !== '' && countDeviceInterfaces(allInterfaces.value, form.sourceDeviceId) === 0)
  const destinationHasNoInterfacesAtAll = computed(() => form.destinationDeviceId !== '' && countDeviceInterfaces(allInterfaces.value, form.destinationDeviceId) === 0)

  watch(
    () => source.connection(),
    () => {
      Object.assign(form, connectionFormFromSource(source.connection(), source.prefill(), allInterfaces.value))
      resolving.value = false
    },
    { immediate: true },
  )

  // Смена устройства сбрасывает выбранный порт, если он больше не входит в список (иначе можно было бы отправить порт от
  // другого устройства невидимым образом).
  watch(
    () => form.sourceDeviceId,
    () => {
      if (!sourceInterfaces.value.some((i) => i.id === form.source_interface_id)) form.source_interface_id = ''
    },
  )
  watch(
    () => form.destinationDeviceId,
    () => {
      if (!destinationInterfaces.value.some((i) => i.id === form.destination_interface_id)) form.destination_interface_id = ''
    },
  )

  /** Подпись устройства выбранной стороны (пусто — устройство не выбрано или его нет в списке). */
  function endpointDeviceLabel(endpoint: ConnectionEndpoint): string {
    const id = endpoint === 'source' ? form.sourceDeviceId : form.destinationDeviceId
    const device = devicesStore.all.find((d) => d.id === id)
    return device ? connectionDeviceLabel(device) : ''
  }

  return {
    saving,
    errorMessage,
    resolving,
    isEdit,
    form,
    selectedSourceInterface,
    selectedDestinationInterface,
    sourceInterfaces,
    destinationInterfaces,
    deviceOptions,
    sourcePortOptions,
    destinationPortOptions,
    connectionTypeOptions,
    sourceHasNoInterfacesAtAll,
    destinationHasNoInterfacesAtAll,
    endpointDeviceLabel,
  }
}

export type ConnectionDraft = ReturnType<typeof useConnectionDraft>
