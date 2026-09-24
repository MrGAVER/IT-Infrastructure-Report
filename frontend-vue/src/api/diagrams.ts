// Диаграмма топологии сети — контракт узла/ребра и API-эндпоинты раздела 4.4/7 ТЗ
// (backend/app/api/diagrams.py, backend/app/services/diagram_graph.py). Типы зафиксированы по
// ТЗ независимо от того, готов ли в моменте бэкенд (см. раздел 12 ТЗ, "Точка 1 (старт)").
import { api, getStoredToken } from './client'

export type DiagramGroupBy = 'structural_unit' | 'vlan' | 'building' | 'device_category'

export const GROUP_BY_OPTIONS: { value: DiagramGroupBy; label: string }[] = [
  { value: 'structural_unit', label: 'По структурной единице' },
  { value: 'vlan', label: 'По VLAN' },
  { value: 'building', label: 'По зданию' },
  { value: 'device_category', label: 'По категории устройства' },
]

export type DiagramIconShape = 'server' | 'switch' | 'switch_l2' | 'switch_l3' | 'router' | 'firewall' | 'workstation' | 'peripheral' | 'generic'

export interface DiagramIconGenerated {
  mode: 'generated'
  shape: DiagramIconShape
  color: string
  // Путь SVG-глифа формы (viewBox "0 0 12 11") — Фаза 2, п.2 плана доработок экспорта диаграмм:
  // раньше жил только во фронтенде (SHAPE_GLYPHS в DiagramDeviceNode.vue), теперь единственный
  // источник — backend/app/services/diagram_icons.py:SHAPE_GLYPHS, чтобы тот же путь могли
  // нарисовать и .svg/.drawio-экспортёры, не только канвас.
  glyph: string
  port_ticks?: number
  port_overflow?: number
  manufacturer_label: string
  model_label: string
}

export interface DiagramIconCustom {
  mode: 'custom'
  svg_markup: string
}

export type DiagramNodeIcon = DiagramIconGenerated | DiagramIconCustom

export interface DiagramIpAddress {
  address: string
  purpose: string | null
  is_management: boolean
}

interface DiagramNodeBase {
  id: string
  x: number
  y: number
}

export interface DiagramDeviceNode extends DiagramNodeBase {
  type: 'device'
  label: string
  serial_number: string
  system_name: string | null
  category_id: string | null
  manufacturer: string | null
  model: string | null
  ip_addresses: DiagramIpAddress[]
  icon: DiagramNodeIcon
}

export interface DiagramGroupNode extends DiagramNodeBase {
  type: 'group'
  label: string
  device_count: number
}

export type DiagramNode = DiagramDeviceNode | DiagramGroupNode

export interface DiagramInterfaceRef {
  id: string
  name: string
  /** Порядковая позиция среди интерфейсов устройства — присутствует, когда этот конец ребра
   * отрисован как узел устройства со сгенерированным (не custom) значком, в пределах первых 32
   * портов (см. backend/app/services/diagram_icons.py:MAX_PORT_TICKS). Отсутствует, если конец
   * ребра свёрнут в узел-группу (у него нет своих засечек порта) или значок узла — custom SVG.
   * Используется для анкеринга ребра к конкретной засечке порта на канвасе. */
  port_index?: number
}

export interface DiagramVlanRef {
  id: string
  vlan_id: number
  name: string
}

export interface DiagramEdge {
  id: string
  source_node_id: string
  source_interface: DiagramInterfaceRef | null
  target_node_id: string
  target_interface: DiagramInterfaceRef | null
  connection_type: string | null
  is_active: boolean
  vlans: DiagramVlanRef[]
}

export interface DiagramViewport {
  zoom: number
  pan_x: number
  pan_y: number
}

export interface SavedDiagramSummary {
  id: string
  name: string
  description: string | null
  scope_filter: Record<string, unknown>
  group_by: DiagramGroupBy
  collapse_threshold: number
  last_export_format: string | null
  created_at: string | null
  updated_at: string | null
}

export interface SavedDiagramDetail extends SavedDiagramSummary {
  nodes: DiagramNode[]
  edges: DiagramEdge[]
  viewport: DiagramViewport | null
}

export interface CreateDiagramPayload {
  name: string
  description?: string | null
  scope_filter?: Record<string, unknown>
  group_by?: DiagramGroupBy
  collapse_threshold?: number
}

export interface NodePositions {
  [nodeId: string]: { x: number; y: number }
}

export interface UpdateLayoutPayload {
  node_positions: NodePositions
  viewport?: DiagramViewport
}

export interface GroupStateResult {
  group_key: string
  is_collapsed: boolean
  device_count: number
  custom_threshold: number | null
}

export type DiagramExportFormat = 'drawio' | 'vsdx' | 'svg'

export function listDiagrams() {
  return api.get<SavedDiagramSummary[]>('/diagrams')
}

export function createDiagram(payload: CreateDiagramPayload) {
  return api.post<SavedDiagramSummary>('/diagrams', payload)
}

export function getDiagram(id: string) {
  return api.get<SavedDiagramDetail>(`/diagrams/${id}`)
}

export function updateDiagramLayout(id: string, payload: UpdateLayoutPayload) {
  return api.put<{ status: string }>(`/diagrams/${id}/layout`, payload)
}

export function renameDiagram(id: string, name: string) {
  return api.put<SavedDiagramSummary>(`/diagrams/${id}/rename`, { name })
}

export function updateGroupState(id: string, groupKey: string, payload: { is_collapsed?: boolean; custom_threshold?: number | null }) {
  return api.put<GroupStateResult>(`/diagrams/${id}/groups/${encodeURIComponent(groupKey)}`, payload)
}

export function regenerateDiagram(id: string) {
  return api.post<SavedDiagramDetail>(`/diagrams/${id}/regenerate`, {})
}

export function duplicateDiagram(id: string) {
  return api.post<SavedDiagramSummary>(`/diagrams/${id}/duplicate`, {})
}

export function deleteDiagram(id: string) {
  return api.delete<{ status: string }>(`/diagrams/${id}`)
}

/**
 * Скачивание файла экспорта — НЕ через api.get() (тот всегда делает res.json()) и НЕ через
 * простую навигацию `<a href>` (как /reports/download в reports.ts): тот путь не прикладывает
 * заголовок Authorization и работает только пока auth выключен (см. backend/app/services/auth.py
 * — переключаемая опция). Экспорт диаграммы всегда идёт через fetch() с явным заголовком, чтобы
 * скачивание не ломалось молча, как только администратор включит вход по паролю.
 */
export async function exportDiagram(id: string, format: DiagramExportFormat): Promise<{ blob: Blob; filename: string }> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`/api/v1/diagrams/${id}/export?format=${format}`, { headers })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || res.statusText)
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const asciiMatch = disposition.match(/filename="([^"]+)"/)
  const filename = asciiMatch?.[1] ?? `diagram.${format}`
  return { blob: await res.blob(), filename }
}
