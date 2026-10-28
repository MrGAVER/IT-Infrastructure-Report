// Фикстуры строк редактора портов для тестов utils/interface*.ts и composables/useInterface*.ts.
import type { InterfaceDraftRow, PortConflictInfo, VLANDefinition } from '../../api/types'

export function makeRow(patch: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
  return {
    name: 'Gi0/1',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    all_vlans: false,
    vlan_mode: 'access',
    ips: [],
    open_ports: [],
    ...patch,
  }
}

export function makeVlan(id: string, vlanId: number, name = `VLAN ${vlanId}`, domainName = ''): VLANDefinition {
  return { id, vlan_id: vlanId, name, description: '', domain_id: null, domain_name: domainName, devices: [] }
}

export function makeConflict(patch: Partial<PortConflictInfo> = {}): PortConflictInfo {
  return {
    otherInterfaceId: 'if-9',
    otherDeviceName: 'sw-02',
    otherInterfaceName: 'Gi0/9',
    flagsDiffer: false,
    vlanModeDiffer: false,
    allVlansDiffer: false,
    other: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: false },
    ...patch,
  }
}
