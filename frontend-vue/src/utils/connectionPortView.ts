// Сверка конфигурации пары портов в форме подключения (ConnectionFormModal.vue): что показать по ответу сервера или, пока ответа
// нет, по каталогу интерфейсов. Чистые функции без Vue и без обращений к API.
import type { DeviceInterface, PortConfigFacet, PortConfigPreview, PortConfigStatus, PortRole, VlanMode } from '../api/types'
import { formatVlans, hasRoleMismatch, modeLabel, portRoleOf, roleLabel } from './portConfig'

export interface ConfigSide {
  id: string
  name: string
  role: PortRole
  /** null — ответа сервера нет, режим и VLAN неизвестны. */
  mode: VlanMode | null
  vlans: number[] | null
}

export interface ConfigView {
  status: PortConfigStatus
  diff: PortConfigFacet[]
  source: ConfigSide
  destination: ConfigSide
}

/** Решение пользователя по расхождению конфигурации портов (кнопки блока «Что сделать перед сохранением?»). */
export type MismatchResolution = 'keep-source' | 'keep-destination' | 'mode-keep-source' | 'mode-keep-destination' | 'approve'

/**
 * Вид сверки пары портов. Ответ сервера (preview) берётся, только если он относится именно к выбранной паре — иначе (выбрали
 * другой порт) он устарел. До ответа или если запрос не удался сверяются хотя бы роли по каталогу — чтобы не сохранять расхождение
 * ролей молча; режим и VLAN в таком случае неизвестны (null). Пара не выбрана — null.
 */
export function buildConfigView(source: DeviceInterface | null, destination: DeviceInterface | null, preview: PortConfigPreview | null): ConfigView | null {
  if (!source || !destination) return null
  if (preview && preview.source.interface_id === source.id && preview.destination.interface_id === destination.id) {
    return {
      status: preview.status,
      diff: preview.diff,
      source: { id: source.id, name: source.name, role: preview.source.role, mode: preview.source.mode, vlans: preview.source.vlans },
      destination: {
        id: destination.id,
        name: destination.name,
        role: preview.destination.role,
        mode: preview.destination.mode,
        vlans: preview.destination.vlans,
      },
    }
  }
  const rolesDiffer = hasRoleMismatch(source, destination)
  return {
    status: rolesDiffer ? 'mismatch' : 'ok',
    diff: rolesDiffer ? ['role'] : [],
    source: { id: source.id, name: source.name, role: portRoleOf(source), mode: null, vlans: null },
    destination: { id: destination.id, name: destination.name, role: portRoleOf(destination), mode: null, vlans: null },
  }
}

/** «Роль · режим · VLAN …» одной стороны (режим и VLAN — только если известны). */
export function sideLabel(side: ConfigSide): string {
  return [roleLabel(side.role), ...(side.mode ? [modeLabel(side.mode)] : []), ...(side.vlans ? [`VLAN ${formatVlans(side.vlans)}`] : [])].join(' · ')
}

/** Различается ли указанная грань (роль, режим, VLAN) у пары портов. */
export function viewDiffers(view: ConfigView | null, facet: PortConfigFacet): boolean {
  return view?.diff.includes(facet) ?? false
}

/** Режим можно выровнять каскадом: он различается и известен (по ответу сервера) у обоих портов. Окно портов («Управлять портами») нужно только для VLAN. */
export function canAlignMode(view: ConfigView | null): boolean {
  return viewDiffers(view, 'mode') && !!view?.source.mode && !!view.destination.mode
}
