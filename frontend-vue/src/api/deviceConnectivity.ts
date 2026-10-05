// Подключаемость портов устройства: данные считает сервер (backend services/device_connectivity.py), а не
// клиент по общим спискам интерфейсов и подключений, которые грузятся целиком с потолком в 1000 записей.
// Используется формой устройства (блок «Подключение» в строке порта).
import { api } from './client'
import type { VlanMode } from './types'

/** Порт устройства из GET /devices/{id}/free-interfaces. `occupied` — у порта есть активное подключение;
 * такие порты приходят только если запрошены через include (текущий сосед, порты, освобождаемые формой). */
export interface FreeInterface {
  id: string
  name: string
  is_management: boolean
  is_data_transfer: boolean
  vlan_mode: VlanMode
  occupied: boolean
}

export interface FreeInterfacesPage {
  items: FreeInterface[]
  total: number
  offset: number
  limit: number
}

/** Действующее подключение порта устройства из GET /devices/{id}/interface-connections. */
export interface DeviceInterfaceConnection {
  interface_id: string
  connection_id: string
  connection_type_id: string
  description: string | null
  peer_interface_id: string
  peer_interface_name: string
  peer_device_id: string
  peer_device_name: string
  peer_is_management: boolean
  peer_is_data_transfer: boolean
  peer_vlan_mode: VlanMode
}

/** Размер страницы при полной загрузке портов устройства (сервер принимает до 500). */
export const FREE_INTERFACES_PAGE_SIZE = 200

export interface FreeInterfacesQuery {
  /** Подстрока имени порта без учёта регистра. */
  q?: string
  /** id портов этого устройства, которые вернуть даже занятыми. */
  include?: readonly string[]
  offset?: number
  limit?: number
}

/** Одна страница свободных портов устройства. */
export function fetchFreeInterfacesPage(deviceId: string, { q, include = [], offset = 0, limit = FREE_INTERFACES_PAGE_SIZE }: FreeInterfacesQuery = {}): Promise<FreeInterfacesPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (q?.trim()) params.set('q', q.trim())
  for (const id of include) params.append('include', id)
  return api.get<FreeInterfacesPage>(`/devices/${encodeURIComponent(deviceId)}/free-interfaces?${params}`)
}

/**
 * Все свободные порты устройства (плюс запрошенные через include), страница за страницей: размер ответа
 * ограничен, а список не обрезается потолком общих списков. Останавливается, когда набрано `total` портов
 * либо сервер вернул пустую страницу (защита от зацикливания, если набор меняется между запросами).
 *
 * @example
 * const ports = await fetchAllFreeInterfaces(peerDeviceId, [currentPeerPortId])
 */
export async function fetchAllFreeInterfaces(deviceId: string, include: readonly string[] = []): Promise<FreeInterface[]> {
  const all: FreeInterface[] = []
  for (;;) {
    const page = await fetchFreeInterfacesPage(deviceId, { include, offset: all.length })
    all.push(...page.items)
    if (!page.items.length || all.length >= page.total) return all
  }
}

/** Действующие подключения портов устройства, у каждого — сведения о соседнем порте и устройстве. */
export async function fetchDeviceInterfaceConnections(deviceId: string): Promise<DeviceInterfaceConnection[]> {
  const res = await api.get<{ items: DeviceInterfaceConnection[] }>(`/devices/${encodeURIComponent(deviceId)}/interface-connections`)
  return res.items
}
