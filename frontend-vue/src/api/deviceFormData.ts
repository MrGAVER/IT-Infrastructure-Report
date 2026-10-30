// Загрузка вложенных данных устройства для формы (DeviceFormModal.vue): ПО, порты и их группы, VLAN устройства, членство в
// доменах VLAN, допустимые VLAN типа и подключения портов. Для копии строки донора превращаются в «новые» — без id.
import { listAllResource } from './client'
import { loadDeviceInterfaceDraftRows, loadDeviceInterfaceGroups } from './deviceInterfaces'
import { fetchDeviceInterfaceConnections, type DeviceInterfaceConnection } from './deviceConnectivity'
import { loadDeviceTypeVlanIds } from './portVlans'
import type {
  DeployedSoftware,
  Device,
  DeviceVLAN,
  DeviceVlanDraftRow,
  InterfaceDraftRow,
  InterfaceGroupDraft,
  SoftwareAssetDraftRow,
  VLANDomainDeviceLink,
} from './types'
import { stripIds } from '../utils/copyEntity'
import { copyInterfaceRows, toDeviceVlanDraftRow, toSoftwareDraftRow } from '../utils/deviceForm'
import { cloneGroupsForCopy } from '../utils/interfaceGroups'
import { attachConnectionDrafts } from '../utils/interfaceConnections'

export interface DeviceNestedData {
  softwareAssets: SoftwareAssetDraftRow[]
  interfaces: InterfaceDraftRow[]
  interfaceGroups: InterfaceGroupDraft[]
  /** Строки «VLAN устройства» в порядке сервера (упорядочивает форма: номера VLAN знает её стор). */
  vlanRows: DeviceVlanDraftRow[]
  /** Домены VLAN, в которых состоит устройство-источник. */
  domainIds: string[]
  /** VLAN, разрешённые для типа устройства-источника. */
  typeVlanIds: Set<string>
  /** Действующие подключения портов (у копии пусто: подключений донора она не наследует). */
  connections: DeviceInterfaceConnection[]
}

/**
 * Вложенные данные устройства-источника: редактируемого (isCopy = false) или донора копирования (isCopy = true).
 * ensureVlansLoaded — загрузка справочника VLAN: идёт в том же Promise.all (форме нужны номера VLAN для упорядочивания строк).
 *
 * Всё грузится атомарно, одним Promise.all (а не отдельным watch на тип устройства), чтобы список допустимых VLAN порта не
 * пересчитывался с неполными данными между двумя разными по времени загрузками. Ошибка любого запроса не глотается — её
 * показывает форма.
 */
export async function loadDeviceNestedData(source: Device, isCopy: boolean, ensureVlansLoaded: () => Promise<unknown>): Promise<DeviceNestedData> {
  const [software, ifaceRows, ifaceGroups, vlans, domainLinks, typeVlanIds, deviceConnections] = await Promise.all([
    listAllResource<DeployedSoftware>('deployed-software', { owner_type: 'physical_device', owner_id: source.id }),
    // Загрузка + сборка InterfaceDraftRow[] вынесена в api/deviceInterfaces.ts — тот же помощник использует DevicePortsModal.vue
    // (управление портами с экрана «Подключения»). Открытые порты каждого интерфейса приходят уже вложенными в ifaceRows[].open_ports.
    loadDeviceInterfaceDraftRows(source.id),
    loadDeviceInterfaceGroups(source.id),
    listAllResource<DeviceVLAN>('device-vlans', { physical_device_id: source.id }),
    listAllResource<VLANDomainDeviceLink>('vlan-domain-devices', { physical_device_id: source.id }),
    loadDeviceTypeVlanIds(source.device_type_id),
    // Действующие подключения портов устройства — с сервера, а не из общего списка подключений (потолок 1000 записей): по ним
    // строятся черновики подключений и снимок для отправки только изменённого. Копия устройства подключений не наследует.
    isCopy ? Promise.resolve([] as DeviceInterfaceConnection[]) : fetchDeviceInterfaceConnections(source.id),
    ensureVlansLoaded(),
  ])

  const softwareRows = software.items.map(toSoftwareDraftRow)
  const vlanRows = vlans.items.map(toDeviceVlanDraftRow)
  let interfaces = isCopy ? copyInterfaceRows(ifaceRows) : attachConnectionDrafts(ifaceRows, deviceConnections)
  let interfaceGroups = ifaceGroups
  // Копия: у нового устройства нет групп донора — группы создаются заново (без id, под новыми ключами), а порты перевязываются на них.
  if (isCopy) {
    const cloned = cloneGroupsForCopy(ifaceGroups, interfaces)
    interfaceGroups = cloned.groups
    interfaces = cloned.rows
  }
  return {
    softwareAssets: isCopy ? stripIds(softwareRows) : softwareRows,
    interfaces,
    interfaceGroups,
    vlanRows: isCopy ? stripIds(vlanRows) : vlanRows,
    domainIds: domainLinks.items.map((l) => l.domain_id),
    typeVlanIds,
    connections: deviceConnections,
  }
}
