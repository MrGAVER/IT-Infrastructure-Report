// Общие помощники спеков composables/useDevice*.ts (форма устройства): сторы Pinia с заданным состоянием и черновик формы.
import { vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { Device, VLANDefinition, VLANDomain } from '../../api/types'
import { useDevicesStore } from '../../stores/devices'
import { useVLANDomainsStore } from '../../stores/vlanDomains'
import { useVLANsStore } from '../../stores/vlans'
import { useDeviceDraft } from '../useDeviceDraft'

/** Свежая Pinia; reload() сторов VLAN, доменов и устройств заменены шпионами (без обращения к API). */
export function setupStores() {
  setActivePinia(createPinia())
  const vlans = useVLANsStore()
  const domains = useVLANDomainsStore()
  const devices = useDevicesStore()
  const spies = {
    vlansReload: vi.spyOn(vlans, 'reload').mockResolvedValue(undefined),
    vlansEnsureLoaded: vi.spyOn(vlans, 'ensureLoaded').mockResolvedValue(undefined),
    domainsReload: vi.spyOn(domains, 'reload').mockResolvedValue(undefined),
    domainsEnsureLoaded: vi.spyOn(domains, 'ensureLoaded').mockResolvedValue(undefined),
    devicesReload: vi.spyOn(devices, 'reload').mockResolvedValue(undefined),
  }
  return { vlans, domains, devices, spies }
}

export function setVlanDefinitions(vlans: ReturnType<typeof useVLANsStore>, definitions: VLANDefinition[]) {
  const byNumber = new Map<number, VLANDefinition[]>()
  for (const d of definitions) byNumber.set(d.vlan_id, [...(byNumber.get(d.vlan_id) ?? []), d])
  vlans.groups = [...byNumber].map(([vlan_id, defs]) => ({ vlan_id, definitions: defs }))
}

export function vlanDef(id: string, vlanId: number, domainId: string | null = null): VLANDefinition {
  return { id, vlan_id: vlanId, name: `VLAN ${vlanId}`, description: '', domain_id: domainId, domain_name: domainId ? `dom ${domainId}` : '', devices: [] }
}

export function domain(id: string, name = `Домен ${id}`): VLANDomain {
  return { id, name } as unknown as VLANDomain
}

export function deviceOf(patch: Partial<Device> = {}): Device {
  return { id: 'dev-1', device_type_id: 't-sw', stack_id: null, ...patch } as Device
}

/** Черновик формы с заданным «редактируемым устройством» (null — создание). */
export function makeDraft(device: Device | null = null) {
  return useDeviceDraft(() => device)
}
