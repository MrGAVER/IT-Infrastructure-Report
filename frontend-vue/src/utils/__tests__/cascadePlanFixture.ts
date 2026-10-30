// Фикстуры плана каскадной смены режима порта для тестов (форма ответа сервера —
// backend/app/services/vlan_mode_cascade.py, тип — api/vlanModeCascade.ts).
import type { CascadeGroupChange, CascadePortChange, CascadeVlanRef, VlanModeCascadePlan } from '../../api/vlanModeCascade'

export function vlanRef(vlanId: number, name = ''): CascadeVlanRef {
  return { id: `v${vlanId}`, vlan_id: vlanId, name }
}

export function portChange(patch: Partial<CascadePortChange> = {}): CascadePortChange {
  return {
    id: 'if-2',
    name: 'Gi0/2',
    device_id: 'dev-2',
    device_name: 'sw-02',
    deferred: false,
    from_mode: 'trunk',
    to_mode: 'access',
    vlans_before: [],
    vlans_after: [],
    dropped_vlans: [],
    ...patch,
  }
}

export function groupChange(patch: Partial<CascadeGroupChange> = {}): CascadeGroupChange {
  return {
    ...portChange({ id: 'g9', name: 'Магистраль' }),
    ports: [
      { id: 'if-2', name: 'Gi0/2' },
      { id: 'if-4', name: 'Gi0/4' },
    ],
    ...patch,
  }
}

/** По умолчанию — тривиальный план: один порт соседа на другом устройстве, без групп и снимаемых VLAN. */
export function makePlan(patch: Partial<VlanModeCascadePlan> = {}): VlanModeCascadePlan {
  return {
    target_mode: 'access',
    start_interface_id: 'if-2',
    edited_device_id: null,
    empty: false,
    groups: [],
    ports: [portChange()],
    devices: [{ id: 'dev-2', name: 'sw-02', deferred: false, port_count: 1, group_count: 0 }],
    totals: { ports: 1, devices: 1, groups: 0, deferred_ports: 0, immediate_ports: 1, immediate_devices: 1, dropped_vlans: 0 },
    warnings: [],
    hash: 'hash-1',
    ...patch,
  }
}
