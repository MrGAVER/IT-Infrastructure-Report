// Сохранение вложенных списков ВМ — открытых портов, IP-адресов и программных активов — одним
// атомарным запросом на список: PUT /vms/{id}/open-ports | /ip-addresses | /deployed-software
// (см. backend/app/services/crud/owned_rows.py: sync_vm_open_ports, sync_vm_ip_addresses,
// sync_vm_deployed_software). Сервер сам сравнивает присланный список с тем, что уже есть в БД, по id:
// строка с id обновляет существующую запись, без id создаёт новую, записи, которых в списке нет,
// удаляются. Поэтому форма ВМ больше не удаляет и не создаёт записи заново при каждом сохранении —
// id и дата создания сохраняются, в журнал попадает только реальное изменение, а любая ошибка
// откатывает весь список целиком. Модуль, как и deviceInterfaces.ts, не знает про Pinia-сторы.
import { api } from './client'
import type { DeployedSoftware, IPAddress, OpenPort, OpenPortDraftRow, SoftwareAssetDraftRow, VmIpDraftRow } from './types'

/**
 * Приводит открытые порты ВМ к списку rows и возвращает сохранённые порты по возрастанию номера.
 *
 * Строка без выбранной записи справочника (пустой плейсхолдер формы) не отправляется. port/protocol
 * в запрос не входят вовсе — сервер выводит их из protocol_catalog_id. Пустой rows — не ошибка:
 * сервер удалит все порты ВМ (ВМ без открытых портов).
 *
 * @example
 * const saved = await syncVmOpenPorts('vm-123', [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }])
 */
export async function syncVmOpenPorts(vmId: string, rows: readonly OpenPortDraftRow[]): Promise<OpenPort[]> {
  const { items } = await api.put<{ items: OpenPort[] }>(`/vms/${vmId}/open-ports`, {
    open_ports: rows
      .filter((row) => row.protocol_catalog_id)
      .map((row) => ({
        id: row.id,
        protocol_catalog_id: row.protocol_catalog_id,
        transport_protocol: row.transport_protocol || 'TCP',
        description: row.description || null,
      })),
  })
  return items
}

/**
 * Приводит IP-адреса ВМ к списку rows и возвращает сохранённые адреса.
 *
 * Строка с пустым адресом (плейсхолдер формы) не отправляется. Пустой префикс уходит как null,
 * непустой — числом; формат IPv4 и диапазон префикса проверяет и форма, и сервер (422). Пустой rows —
 * не ошибка: сервер удалит все IP-адреса ВМ.
 *
 * @example
 * const saved = await syncVmIpAddresses('vm-123', [{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: '', is_management: true }])
 */
export async function syncVmIpAddresses(vmId: string, rows: readonly VmIpDraftRow[]): Promise<IPAddress[]> {
  const { items } = await api.put<{ items: IPAddress[] }>(`/vms/${vmId}/ip-addresses`, {
    ip_addresses: rows
      .filter((row) => row.ip_address.trim())
      .map((row) => ({
        id: row.id,
        ip_address: row.ip_address.trim(),
        prefix_length: row.prefix_length === '' ? null : Number(row.prefix_length),
        purpose: row.purpose || null,
        is_management: row.is_management,
      })),
  })
  return items
}

/**
 * Приводит развёрнутое на ВМ ПО к списку rows и возвращает сохранённые записи.
 *
 * Строка без выбранного программного актива (плейсхолдер формы) не отправляется. Пустая версия
 * уходит как null. Пустой rows — не ошибка: сервер удалит всё ПО ВМ.
 *
 * @example
 * const saved = await syncVmDeployedSoftware('vm-123', [{ id: 'sw-1', software_asset_id: 'asset-nginx', version: '1.25' }])
 */
export async function syncVmDeployedSoftware(vmId: string, rows: readonly SoftwareAssetDraftRow[]): Promise<DeployedSoftware[]> {
  const { items } = await api.put<{ items: DeployedSoftware[] }>(`/vms/${vmId}/deployed-software`, { deployed_software: toDeployedSoftwarePayload(rows) })
  return items
}

/** Строки редактора ПО → payload синхронизации (общий для ВМ и физических устройств, см.
 * api/deviceDeployedSoftware.ts): строки без выбранного актива отбрасываются, пустая версия → null. */
export function toDeployedSoftwarePayload(rows: readonly SoftwareAssetDraftRow[]) {
  return rows
    .filter((row) => row.software_asset_id)
    .map((row) => ({ id: row.id, software_asset_id: row.software_asset_id, version: row.version || null }))
}
