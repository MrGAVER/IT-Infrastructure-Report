// Сохранение программных активов физического устройства одним атомарным запросом
// PUT /devices/{id}/deployed-software (см. backend/app/services/crud/owned_rows.py:sync_device_deployed_software)
// — тем же способом, что и у ВМ (api/vmNestedLists.ts). Раньше DeviceFormModal.vue при каждом
// сохранении удалял всё ПО устройства и создавал его заново: новые id и даты создания, 2N+1 запросов,
// потерянное ПО при сбое посередине. Теперь записи с id обновляются на месте, без id создаются, а
// убранные в форме удаляет сервер.
import { api } from './client'
import { toDeployedSoftwarePayload } from './vmNestedLists'
import type { DeployedSoftware, SoftwareAssetDraftRow } from './types'

/**
 * Приводит программные активы устройства к списку rows и возвращает сохранённые записи.
 *
 * Строка без выбранного актива (плейсхолдер формы) не отправляется, пустая версия уходит как null.
 * Пустой rows — не ошибка: сервер удалит всё ПО устройства.
 *
 * @example
 * const saved = await syncDeviceDeployedSoftware('dev-123', [{ id: 'sw-1', software_asset_id: 'asset-ad', version: '2022' }])
 */
export async function syncDeviceDeployedSoftware(deviceId: string, rows: readonly SoftwareAssetDraftRow[]): Promise<DeployedSoftware[]> {
  const { items } = await api.put<{ items: DeployedSoftware[] }>(`/devices/${deviceId}/deployed-software`, { deployed_software: toDeployedSoftwarePayload(rows) })
  return items
}
