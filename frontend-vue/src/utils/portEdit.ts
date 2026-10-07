// Правка порта на дашборде «Подключения» — чистая логика окна (components/PortConfigEditModal.vue):
// черновик роли, режима и набора VLAN, приведение набора к режиму, сравнение с соседом и тело запроса.
// Без Vue и сети: правила (допустимые VLAN, «в access не более одного VLAN», группа портов, которая
// задаёт режим и VLAN) окончательно проверяет сервер (backend/app/services/port_edit.py), здесь —
// то, что нужно окну, чтобы не дать выбрать заведомо неверное и показать, что получится.
import type { PortConfigFacet, PortRole, VLANDefinition, VlanMode } from '../api/types'

/** Что редактируется: роль, режим и набор VLAN (id записей справочника) одного порта. */
export interface PortDraft {
  role: PortRole
  mode: VlanMode
  vlanIds: string[]
}

export function cloneDraft(draft: PortDraft): PortDraft {
  return { role: draft.role, mode: draft.mode, vlanIds: [...draft.vlanIds] }
}

/** Совпадают ли наборы без учёта порядка и повторов. */
export function sameIds(a: readonly string[], b: readonly string[]): boolean {
  const left = new Set(a)
  const right = new Set(b)
  return left.size === right.size && [...left].every((id) => right.has(id))
}

/** Записи справочника с данными номерами VLAN: из нескольких записей с одним номером берётся первая в
 * порядке `options`. Номера, которых нет среди доступных устройству, пропускаются — их вернёт `missing`. */
export function vlanIdsForNumbers(options: readonly VLANDefinition[], numbers: readonly number[]): { ids: string[]; missing: number[] } {
  const ids: string[] = []
  const missing: number[] = []
  for (const number of [...new Set(numbers)].sort((a, b) => a - b)) {
    const found = options.find((o) => o.vlan_id === number)
    if (found) ids.push(found.id)
    else missing.push(number)
  }
  return { ids, missing }
}

/** Номера VLAN выбранных записей по возрастанию. */
export function numbersOf(options: readonly VLANDefinition[], ids: readonly string[]): number[] {
  const byId = new Map(options.map((o) => [o.id, o.vlan_id]))
  return [...new Set(ids.map((id) => byId.get(id)).filter((n): n is number => n !== undefined))].sort((a, b) => a - b)
}

/** Набор VLAN после смены режима: в access остаётся один VLAN с наименьшим номером (как в форме
 * устройства и в каскаде смены режима), в trunk набор сохраняется как есть. */
export function adaptVlanIdsToMode(options: readonly VLANDefinition[], ids: readonly string[], mode: VlanMode): string[] {
  if (mode !== 'access' || ids.length <= 1) return [...ids]
  const byId = new Map(options.map((o) => [o.id, o.vlan_id]))
  const lowest = [...ids].sort((a, b) => (byId.get(a) ?? Infinity) - (byId.get(b) ?? Infinity) || a.localeCompare(b))[0]
  return [lowest]
}

/** Конфигурация порта-соседа для сравнения: роль, режим, номера VLAN. */
export interface NeighborConfig {
  role: PortRole | null
  mode: VlanMode | null
  vlans: readonly number[]
}

/** Чем черновик будет отличаться от соседа — те же грани и порядок, что у сверки на сервере
 * (services/port_config.config_differences): роль, режим, VLAN. Пусто — порты согласованы. */
export function differencesFromNeighbor(
  draft: PortDraft,
  draftVlanNumbers: readonly number[],
  neighbor: NeighborConfig,
): PortConfigFacet[] {
  const facets: PortConfigFacet[] = []
  if (neighbor.role !== null && draft.role !== neighbor.role) facets.push('role')
  if (neighbor.mode !== null && draft.mode !== neighbor.mode) facets.push('mode')
  const left = [...new Set(draftVlanNumbers)].sort((a, b) => a - b)
  const right = [...new Set(neighbor.vlans)].sort((a, b) => a - b)
  if (left.length !== right.length || left.some((n, i) => n !== right[i])) facets.push('vlans')
  return facets
}

/** Тело PUT /interfaces/{id}/port-config для роли и VLAN. Режим сюда не входит — его меняет каскад
 * (до этого запроса); поле `mode` в теле лишь сообщает серверу, для какого режима выбран набор.
 *
 * `modeChanged` — режим меняли в этой правке: после каскада набор VLAN порта мог быть урезан, поэтому
 * желаемый набор отправляется заново и целиком, даже если он совпадает с исходным. `vlansLocked` — порт в
 * группе, которая задаёт режим и VLAN: набор не отправляется вовсе (группа — источник истины).
 * null — отправлять нечего. */
export function buildPortConfigPatch(
  initial: PortDraft,
  draft: PortDraft,
  { modeChanged, vlansLocked }: { modeChanged: boolean; vlansLocked: boolean },
): { role?: PortRole; vlan_ids?: string[]; mode: VlanMode } | null {
  const patch: { role?: PortRole; vlan_ids?: string[]; mode: VlanMode } = { mode: draft.mode }
  if (draft.role !== initial.role) patch.role = draft.role
  if (!vlansLocked && (modeChanged || !sameIds(draft.vlanIds, initial.vlanIds))) patch.vlan_ids = [...new Set(draft.vlanIds)]
  return patch.role !== undefined || patch.vlan_ids !== undefined ? patch : null
}

/** Что-нибудь отличается от исходного состояния (роль, режим или набор VLAN). */
export function isDirty(initial: PortDraft, draft: PortDraft): boolean {
  return initial.role !== draft.role || initial.mode !== draft.mode || !sameIds(initial.vlanIds, draft.vlanIds)
}

/** Проверка до отправки — те же правила, что на сервере. Текст ошибки или null. */
export function validateDraft(draft: PortDraft, { vlansLocked }: { vlansLocked: boolean }): string | null {
  if (!vlansLocked && draft.mode === 'access' && new Set(draft.vlanIds).size > 1) return 'В режиме access у порта может быть не более одного VLAN'
  return null
}
