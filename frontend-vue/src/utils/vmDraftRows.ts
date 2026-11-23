// Строки черновика вложенных списков виртуальной машины (VMFormModal.vue): ответ API → поля формы (пустое значение — пустая строка).
import type { DeployedSoftware, IPAddress, OpenPort, OpenPortDraftRow, SoftwareAssetDraftRow, VmIpDraftRow } from '../api/types'

export function toIpDraftRow(x: IPAddress): VmIpDraftRow {
  return {
    id: x.id,
    ip_address: x.ip_address,
    prefix_length: x.prefix_length == null ? '' : String(x.prefix_length),
    purpose: x.purpose ?? '',
    is_management: x.is_management,
  }
}

export function toOpenPortDraftRow(x: OpenPort): OpenPortDraftRow {
  return {
    id: x.id,
    protocol_catalog_id: x.protocol_catalog_id ?? '',
    transport_protocol: x.transport_protocol,
    description: x.description ?? '',
  }
}

export function toSoftwareDraftRow(x: DeployedSoftware): SoftwareAssetDraftRow {
  return { id: x.id, software_asset_id: x.software_asset_id, version: x.version ?? '' }
}
