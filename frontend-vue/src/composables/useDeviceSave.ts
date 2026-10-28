// Сохранение формы устройства (DeviceFormModal.vue).
//
// Повторяет логику подтверждения конфликтов из прежнего vanilla-фронтенда (saveForm, до 2.60.0) для консистентности UX: два
// специфичных кода 409-ошибки (см. backend/app/constants.py:ErrorCode) предлагают подтверждение через window.confirm() и
// повторную отправку с флагом, вместо того чтобы просто показать ошибку и заставить пользователя вводить всё заново.
import { ref, type ComputedRef, type Ref } from 'vue'
import { ApiError, createResource, ErrorCode, updateResource } from '../api/client'
import { syncDeviceDeployedSoftware } from '../api/deviceDeployedSoftware'
import { fetchDeviceInterfaceConnections } from '../api/deviceConnectivity'
import { persistDeviceInterfaces } from '../api/deviceInterfaces'
import { persistDeviceVlans } from '../api/deviceVlans'
import type { Device, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsStore } from '../stores/connections'
import { useDevicesStore } from '../stores/devices'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useVLANsStore } from '../stores/vlans'
import { deviceFormPayload, deviceVlanKey } from '../utils/deviceForm'
import { validateDeviceDraft } from '../utils/deviceFormValidation'
import { changedConnectionRowIds, hasConnectionChanges } from '../utils/interfaceConnections'
import { buildPortConflictNotice, computePortConflicts, type PortRowLike } from '../utils/portConflicts'
import { findPortSyncNotice } from '../utils/portSyncNotice'
import type { PortConfig } from '../utils/portConflicts'
import { usePortSyncPlanRequest } from './usePortSyncPlanRequest'
import { useToast } from './useToast'
import type { DeviceDomains } from './useDeviceDomains'
import type { DeviceDraft } from './useDeviceDraft'

export interface DeviceSaveDeps {
  /** Редактируемое устройство (null — создание или копия). */
  device: () => Device | null
  /** Роль без права записи (viewer): сохранять нечего. */
  readOnly: Ref<boolean>
  domains: DeviceDomains
  portVlanOptions: ComputedRef<VLANDefinition[]>
  /** Редактор портов: перед записью проверяет расхождения с соседями (false — пользователь отказался сохранять);
   * undefined — редактор ещё не смонтирован (грузится), проверять нечего. */
  reviewNeighbors: (initial: Map<string, PortConfig>) => Promise<boolean> | undefined
  /** Раскрыть блок «VLAN устройства» (ошибка относится к строке, скрытой сворачиванием). */
  expandVlanEditor: () => void
  onSaved: (device: Device) => void
}

export function useDeviceSave(draft: DeviceDraft, deps: DeviceSaveDeps) {
  const catalogs = useCatalogsStore()
  const vlansStore = useVLANsStore()
  const vlanDomainsStore = useVLANDomainsStore()
  const connectionsStore = useConnectionsStore()
  const devicesStore = useDevicesStore()
  const { notify } = useToast()
  const portSyncPlan = usePortSyncPlanRequest()
  const saving = ref(false)

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

  // Программные активы устройства — один атомарный PUT /devices/{id}/deployed-software (см.
  // api/deviceDeployedSoftware.ts): сервер сравнивает список с БД по id, записи с id обновляются на
  // месте, новые создаются, убранные в форме удаляются — без пересоздания всего ПО при каждом
  // сохранении. Новому устройству (создание или копия) без заполненных строк синхронизировать нечего —
  // запрос не отправляется; для существующего пустой список отправляется всегда, чтобы снять ПО,
  // убранное пользователем. `deviceExisted` — устройство существовало до этого сохранения (редактирование
  // или повтор после сбоя): для только что созданного пустой список синхронизировать не нужно.
  async function persistSoftwareAssets(deviceId: string, deviceExisted: boolean) {
    if (!deviceExisted && !draft.softwareAssets.value.some((row) => row.software_asset_id)) return
    await syncDeviceDeployedSoftware(deviceId, draft.softwareAssets.value)
  }

  async function submit() {
    if (deps.readOnly.value) return
    draft.errorMessage.value = null
    const issue = validateDeviceDraft({
      form: draft.form,
      interfaces: draft.interfaces.value,
      interfaceGroups: draft.interfaceGroups.value,
      deviceVlans: draft.deviceVlans.value,
      vlanDefinitions: vlansStore.allDefinitions,
      protocolPortCatalog: catalogs.protocolPortCatalog,
      portVlanIds: new Set(deps.portVlanOptions.value.map((v) => v.id)),
      initialConnections: draft.initialConnections.value,
    })
    if (issue) {
      draft.errorMessage.value = issue.message
      if (issue.expandVlanEditor) deps.expandVlanEditor()
      return
    }

    saving.value = true
    // Расхождение назначения/режима порта с соседом, появившееся в этом сохранении, показываем ДО записи — диалогом с
    // возможностью применить конфигурацию соседа или текущего порта, а не только уведомлением после неё (когда форма
    // уже закрыта). Редактор портов не смонтирован (ещё грузится) — проверять нечего.
    const review = deps.reviewNeighbors(draft.snapshot.portConfigs)
    if (review && !(await review)) {
      saving.value = false
      return
    }
    // Меняются ли подключения портов в этом сохранении (и у каких уже сохранённых портов) — от этого
    // зависит, нужно ли после сохранения обновлять стор подключений (см. ниже).
    const connectionsChanged = hasConnectionChanges(draft.interfaces.value, draft.initialConnections.value)
    const changedConnectionIds = changedConnectionRowIds(draft.interfaces.value, draft.initialConnections.value)
    // Устройство создано именно этим сохранением (а не раньше) — нужно, чтобы при сбое следующих шагов
    // честно сказать об этом пользователю (см. catch ниже).
    let createdByThisSubmit = false
    try {
      let extra: Record<string, unknown> | undefined
      // До трёх попыток: обычная отправка, затем до двух ре-отправок с флагами
      // подтверждения, если пользователь согласился на диалоге.
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const payload = deviceFormPayload(draft.form, extra)
          // Устройство уже есть — редактирование либо повтор после сбоя (см. createdDevice): обновляем его.
          const deviceId = draft.existingDeviceId.value
          const saved = deviceId ? await updateResource<Device>('devices', deviceId, payload) : await createResource<Device>('devices', payload)
          if (!deviceId) {
            draft.createdDevice.value = saved
            createdByThisSubmit = true
          }
          await persistSoftwareAssets(saved.id, deviceId !== null)
          await deps.domains.persistPendingDomainMemberships(saved.id)
          await deps.domains.persistPendingSourceDomains(saved.id)
          // persistDeviceVlans ДО persistDeviceInterfaces (не как раньше) — sync_interfaces на
          // бэкенде проверяет vlan_ids порта против уже сохранённых в БД PhysicalDeviceVLAN (см.
          // allowed_vlans в backend/app/services/crud/interfaces.py). Если VLAN только что добавлен в блок
          // "VLAN устройства" и тут же назначен порту в этом же сохранении, к моменту проверки он
          // должен уже быть в БД — иначе 422 "VLAN не разрешён" на ровном месте для пользователя.
          const deviceVlansChanged = !!deps.device() && deviceVlanKey(draft.deviceVlans.value) !== draft.snapshot.deviceVlanKey
          await persistDeviceVlans(saved.id, draft.deviceVlans.value)
          // Атомарный PUT (не через generic createResource/deleteResource) — см.
          // api/deviceInterfaces.ts:persistDeviceInterfaces.
          const { items: savedInterfaces } = await persistDeviceInterfaces(saved.id, draft.interfaces.value, draft.interfaceGroups.value, draft.initialConnections.value)
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
          await Promise.all([vlansStore.reload(), draft.pendingDomainMemberships.value.size || draft.pendingSourceDomainIds.value.size ? vlanDomainsStore.reload() : Promise.resolve()])
          // Пункт 5: interfaceConflicts считается по черновику interfaces — то есть ровно по тому, что
          // только что сохранено.
          // Подключения портов созданы/изменены этим же сохранением: стор подключений устарел, а у новых портов
          // только сейчас появились id — сверяем с соседями уже сохранённые порты (ответ сервера), а не
          // черновые строки. Без изменений подключений — прежний путь (стор не перезагружаем).
          let noticeRows: PortRowLike[] = draft.interfaces.value
          let noticeConflicts = draft.interfaceConflicts.value
          if (connectionsChanged) {
            // Соседи берутся у сервера для этого устройства, а не из общего списка подключений. Общий список
            // (его читают экраны «Подключения» и схема) обновляем, только если он уже загружен: иначе он и так
            // загрузится свежим при первом обращении.
            draft.savedConnections.value = await fetchDeviceInterfaceConnections(saved.id)
            if (connectionsStore.loaded) await connectionsStore.reload()
            noticeRows = savedInterfaces
            noticeConflicts = computePortConflicts(noticeRows, draft.savedConnections.value)
          }
          const conflictNotice = buildPortConflictNotice(noticeRows, noticeConflicts, draft.snapshot.portConfigs, changedConnectionIds)
          if (conflictNotice) notify(conflictNotice, 'warning')
          deps.onSaved(saved)
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
        draft.errorMessage.value = `Устройство создано, но остальные данные сохранить не удалось: ${reason.replace(/[\s.]+$/, '')}. Исправьте данные и нажмите «Сохранить» ещё раз — устройство будет обновлено, а не создано повторно.`
        await devicesStore.reload()
      } else {
        draft.errorMessage.value = reason
      }
    } finally {
      saving.value = false
    }
  }

  return { saving, submit }
}
