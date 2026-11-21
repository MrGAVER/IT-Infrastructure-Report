// Окна, открываемые из строк дашборда «Подключения»: порты устройства, проверка расхождения ролей/режима/VLAN, правка одного порта и
// план согласования по правилам. Состояние и переходы между окнами вынесены из ConnectionsView.vue без изменения поведения.
import { ref } from 'vue'
import type { Connection } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'

export function useConnectionPortDialogs() {
  const dashboard = useConnectionsDashboardStore()
  const catalogs = useCatalogsStore()

  // Прямое управление портами устройства из строки таблицы — без захода в форму подключения
  // (см. DevicePortsModal.vue). Connection отдаёт только *_interface_id и уже резолвленные
  // *_name (enrich_connections() на бэкенде), без physical_device_id напрямую — id устройства
  // находим через уже загруженный каталог 'interfaces' (ConnectionsView грузит его в onMounted).
  const portsTarget = ref<{ deviceId: string; deviceLabel: string } | null>(null)
  function openPortsForInterface(interfaceId: string, deviceLabel: string) {
    const deviceId = catalogs.indexOf('interfaces').get(interfaceId)?.physical_device_id as string | undefined
    if (!deviceId) return
    portsTarget.value = { deviceId, deviceLabel }
  }
  function closePorts() {
    portsTarget.value = null
  }
  async function onPortsSaved() {
    closePorts()
    // Переименование/добавление порта могло изменить то, что показывает таблица
    // (source_interface_name/destination_interface_name резолвятся один раз при загрузке
    // подключений), поэтому перечитываем список — тот же принцип, что onSaved() ниже.
    await dashboard.refreshAfterChange()
  }

  // Проверка ролей портов-соседей (см. services/port_config.py): строка с расхождением/одобрением
  // открывает модалку, где расхождение одобряют или устраняют.
  const reviewing = ref<Connection | null>(null)
  // Окно плана «Согласовать по правилам» для всех подключений с неодобренным расхождением.
  const syncPlanOpen = ref(false)

  /** Из окна проверки — к настройке режима и VLAN порта: окно проверки закрываем, открываем порты
   * устройства; после их сохранения таблица перечитывается (onPortsSaved), и статус пересчитывает сервер. */
  function manageFromReview(target: { interfaceId: string; deviceLabel: string }) {
    reviewing.value = null
    openPortsForInterface(target.interfaceId, target.deviceLabel)
  }

  // Правка роли, режима и VLAN одного порта подключения (PortConfigEditModal.vue) — из строки таблицы и из окна
  // проверки расхождения. Таблицу после сохранения перечитывает само окно.
  const editing = ref<{ connection: Connection; side: 'source' | 'destination' } | null>(null)
  function editPort(connection: Connection, side: 'source' | 'destination') {
    editing.value = { connection, side }
  }
  function editPortFromReview(side: 'source' | 'destination') {
    const connection = reviewing.value
    reviewing.value = null
    if (connection) editPort(connection, side)
  }
  /** Из окна правки порта — к окну всех портов устройства (например, чтобы изменить группу, задающую VLAN). */
  function manageFromEdit(target: { interfaceId: string; deviceLabel: string }) {
    editing.value = null
    openPortsForInterface(target.interfaceId, target.deviceLabel)
  }

  return {
    portsTarget,
    openPortsForInterface,
    closePorts,
    onPortsSaved,
    reviewing,
    syncPlanOpen,
    manageFromReview,
    editing,
    editPort,
    editPortFromReview,
    manageFromEdit,
  }
}
