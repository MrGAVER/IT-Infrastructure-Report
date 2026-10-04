// Сохранение открытых портов ВМ одним атомарным запросом PUT /vms/{id}/open-ports (см.
// backend/app/services/crud.py:sync_vm_open_ports). Сервер сам сравнивает присланный список с тем,
// что уже есть в БД, по id: строка с id обновляет существующий порт, без id создаёт новый, порты,
// которых в списке нет, удаляются. Поэтому форма ВМ больше не удаляет и не создаёт порты заново при
// каждом сохранении — id и дата создания портов сохраняются, в журнал попадает только реальное
// изменение. Модуль, как и deviceInterfaces.ts, не знает про Pinia-сторы.
import { api } from './client'
import type { OpenPort, OpenPortDraftRow } from './types'

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
