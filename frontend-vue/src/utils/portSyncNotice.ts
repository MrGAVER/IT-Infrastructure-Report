// Нужно ли согласовывать порты подключений устройства после изменения списка его VLAN.
// Порты в состоянии «Все VLAN» подхватывают новый VLAN сами, а согласование с соседями запускается только вручную, поэтому
// подключение молча попадает в расхождения. Здесь предпросмотр плана по подключениям устройства (ничего не записывает)
// превращается в короткое уведомление; сами изменения по-прежнему применяются только после просмотра плана и подтверждения.
import { fetchDeviceInterfaceConnections } from '../api/deviceConnectivity'
import { previewPortSync } from '../api/portSync'
import type { PortSyncSummary } from '../api/types'

/** Не больше подключений за один предпросмотр — как MAX_CONNECTION_IDS на сервере (services/port_sync_reconcile.py). */
export const PORT_SYNC_NOTICE_MAX_CONNECTIONS = 500

export interface PortSyncNotice {
  message: string
  /** Подключения для окна плана; пусто — у устройства их слишком много для точной проверки, план строится по всем расхождениям. */
  connectionIds: string[]
}

const HEAD = 'Список VLAN устройства изменён.'

/**
 * Текст уведомления по итогам предпросмотра; null — согласовывать нечего. «Исключено правилом» (ignored) и «расхождения нет»
 * в счёт не идут: по ним человеку делать нечего.
 *
 * @example
 * describePortSyncNotice({ auto: 2, manual: 1, blocked: 0 })
 * // «Список VLAN устройства изменён. У подключений этого устройства расхождение портов: 3 (автоматически по правилам — 2, вручную — 1).»
 */
export function describePortSyncNotice(summary: Pick<PortSyncSummary, 'auto' | 'manual' | 'blocked'>): string | null {
  const manual = summary.manual + summary.blocked
  const total = summary.auto + manual
  if (total === 0) return null
  const parts: string[] = []
  if (summary.auto > 0) parts.push(`автоматически по правилам — ${summary.auto}`)
  if (manual > 0) parts.push(`вручную — ${manual}`)
  return `${HEAD} У подключений этого устройства расхождение портов: ${total} (${parts.join(', ')}).`
}

/**
 * Ищет подключения устройства, у которых после изменения VLAN нужно согласовать порты. null — уведомлять не о чем.
 * Ошибки API не глотаются: вызывающий решает, как о них сказать (сохранение устройства от этого не зависит).
 */
export async function findPortSyncNotice(deviceId: string): Promise<PortSyncNotice | null> {
  const links = await fetchDeviceInterfaceConnections(deviceId)
  const ids = [...new Set(links.map((link) => link.connection_id))]
  if (ids.length === 0) return null
  if (ids.length > PORT_SYNC_NOTICE_MAX_CONNECTIONS) {
    return { message: `${HEAD} У устройства много подключений — проверьте, не появились ли расхождения портов.`, connectionIds: [] }
  }
  // Нужна только сводка (она по всему плану), поэтому просим одну запись страницы, а не все 300.
  const plan = await previewPortSync({ connection_ids: ids }, { limit: 1 })
  const message = describePortSyncNotice(plan.summary)
  return message ? { message, connectionIds: ids } : null
}
