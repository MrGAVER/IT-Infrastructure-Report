// Загрузка данных в форму устройства (DeviceFormModal.vue): источник — редактируемое устройство (props.device) либо
// «устройство-донор» для копирования (props.copyFrom). При копировании props.device остаётся null — это по-прежнему СОЗДАНИЕ
// нового устройства (сохранение вызовет создание, а не обновление), просто форма стартует не с чистого листа, а с данными
// донора. View, открывающие форму, никогда не передают оба сразу.
import { computed, watch } from 'vue'
import { loadDeviceNestedData } from '../api/deviceFormData'
import { fetchDeviceInterfaceConnections } from '../api/deviceConnectivity'
import { loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Device } from '../api/types'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useVLANsStore } from '../stores/vlans'
import { deviceFormFromSource, deviceVlanKey } from '../utils/deviceForm'
import { sortDeviceVlanRows } from '../utils/deviceVlans'
import { snapshotConnections } from '../utils/interfaceConnections'
import { snapshotPortConfigs } from '../utils/portConflicts'
import { useToast } from './useToast'
import type { DeviceDraft } from './useDeviceDraft'

export interface DeviceLoaderDeps {
  device: () => Device | null
  copyFrom: () => Device | null | undefined
}

export function useDeviceLoader(draft: DeviceDraft, deps: DeviceLoaderDeps) {
  const vlansStore = useVLANsStore()
  const vlanDomainsStore = useVLANDomainsStore()
  const { notifyError } = useToast()

  const copySourceId = computed(() => deps.device()?.id ?? deps.copyFrom()?.id ?? null)

  watch(
    copySourceId,
    async () => {
      // Аудит fix/usability-batch4 (находка №5): инвариант "device и copyFrom не передаются
      // одновременно" раньше был защищён только комментарием выше, не типами и не рантайм-
      // проверкой. Dev-warning — минимальная защита от неверного использования; device выигрывает
      // как более безопасный исход (обычный edit не даст случайно затереть данные копированием).
      if (deps.device() && deps.copyFrom()) {
        console.warn('DeviceFormModal: одновременно переданы device и copyFrom — используется device (режим редактирования)')
      }
      const source = deps.device() ?? deps.copyFrom() ?? null
      const isCopy = !deps.device() && !!deps.copyFrom()
      draft.reset()
      Object.assign(draft.form, deviceFormFromSource(source, isCopy))
      // Пункт 3 правки "домен VLAN": справочник доменов для кнопки "Включить в домен" нужен и при
      // СОЗДАНИИ нового устройства (join-запрос откладывается в pendingDomainMemberships до
      // сохранения — тот же механизм, что уже есть для домена, заведённого через создание VLAN, см.
      // onVlanCreated), поэтому загружается ДО ранней остановки ниже, а не внутри неё как
      // vlansStore (ему нужны данные конкретно существующего устройства).
      vlanDomainsStore.ensureLoaded()
      // Устройства-соседи и их свободные порты блок «Подключение» запрашивает у сервера сам (поиском со страницами),
      // полный список устройств форме не нужен.
      if (!source) return
      draft.loadingNested.value = true
      try {
        const data = await loadDeviceNestedData(source, isCopy, () => vlansStore.ensureLoaded())
        draft.softwareAssets.value = data.softwareAssets
        draft.interfaces.value = data.interfaces
        draft.interfaceGroups.value = data.interfaceGroups
        // При копировании id стёрты — снимок пуст, а у копии всё равно нет подключений и соседей.
        draft.snapshot.portConfigs = snapshotPortConfigs(draft.interfaces.value)
        draft.initialConnections.value = snapshotConnections(draft.interfaces.value)
        draft.savedConnections.value = data.connections
        // Список VLAN устройства упорядочен по номеру VLAN (как открытые порты): vlansStore к этому моменту уже
        // загружен (ensureLoaded выше), так что номера известны.
        draft.deviceVlans.value = sortDeviceVlanRows(data.vlanRows, vlansStore.allDefinitions)
        draft.snapshot.deviceVlanKey = deviceVlanKey(draft.deviceVlans.value)
        // При копировании членство в доменах ещё не существует для НОВОГО устройства — переносим
        // как "предстоит создать при сохранении" (см. persistPendingDomainMemberships, фикс
        // п.1.3.8), а не как уже подтверждённое: иначе availableVlans решит, что устройство
        // уже участник домена, которым оно на самом деле пока не является, а связь так и не
        // создастся, поскольку persistPendingDomainMemberships читает только pendingDomainMemberships.
        if (isCopy) {
          draft.pendingDomainMemberships.value = new Set(data.domainIds)
        } else {
          draft.memberDomainIds.value = new Set(data.domainIds)
        }
        draft.deviceTypeVlanIds.value = data.typeVlanIds
      } catch (err) {
        draft.errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить открытые порты, ПО, интерфейсы и VLAN устройства'
      } finally {
        draft.loadingNested.value = false
      }
    },
    { immediate: true },
  )

  // Смена типа устройства уже после загрузки: допустимые VLAN порта перечитываются под новый тип.
  watch(
    () => draft.form.device_type_id,
    async (deviceTypeId) => {
      // loadingNested гвардит от повторной загрузки в момент самой начальной загрузки устройства
      // (там form.device_type_id меняется синхронно вместе с loadingNested=true в том же тике, а
      // deviceTypeVlanIds уже атомарно загружается вместе с остальными вложенными данными) — этот watch
      // нужен только для случая, когда пользователь меняет тип устройства уже после загрузки.
      if (draft.loadingNested.value) return
      try {
        draft.deviceTypeVlanIds.value = await loadDeviceTypeVlanIds(deviceTypeId)
      } catch (err) {
        // Не даём упасть необработанным отклонением промиса — просто оставляем прежний список
        // допустимых VLAN порта и показываем ошибку, как и везде в этой форме.
        draft.errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить допустимые VLAN для типа устройства'
      }
    },
  )

  // Конфигурация соседних портов изменилась из этой формы («Применить текущую конфигурацию соседу», каскад режима
  // порта): сведения о соседях перечитываются с сервера, чтобы значок расхождения исчез сразу. Ошибка не глотается —
  // без обновления значок остался бы устаревшим.
  async function reloadNeighborConfigs() {
    const deviceId = draft.existingDeviceId.value
    if (!deviceId) return
    try {
      draft.savedConnections.value = await fetchDeviceInterfaceConnections(deviceId)
    } catch (err) {
      notifyError(err)
    }
  }

  return { reloadNeighborConfigs }
}
