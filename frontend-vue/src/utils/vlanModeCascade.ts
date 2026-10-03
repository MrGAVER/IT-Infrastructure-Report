// Перенос изменений каскадной смены режима порта на редактируемое устройство (см.
// api/vlanModeCascade.ts и backend/app/services/vlan_mode_cascade.py).
//
// Сервер не пишет порты и группы устройства с открытой формой — форма сохраняется целиком и
// перезаписала бы запись в обход неё. Он отдаёт их в плане с пометкой deferred, а здесь те же
// изменения вносятся в ЧЕРНОВИК формы: сохранятся вместе с ней (кнопка «Сохранить»).
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../api/types'
import type { CascadeGroupChange, EditedDeviceState, VlanMode, VlanModeCascadePlan } from '../api/vlanModeCascade'
import { applyGroupToRow } from './interfaceGroups'

/** Состояние формы для запросов каскада: режимы сохранённых портов и групп (у новых нет id — в БД их
 * нет, и в области изменения они оказаться не могут). null — форма без устройства (создание). */
export function buildEditedState(deviceId: string | null | undefined, rows: InterfaceDraftRow[], groups: InterfaceGroupDraft[]): EditedDeviceState | null {
  if (!deviceId) return null
  const ports: EditedDeviceState['ports'] = {}
  for (const row of rows) if (row.id) ports[row.id] = row.vlan_mode
  const groupModes: EditedDeviceState['groups'] = {}
  for (const group of groups) if (group.id) groupModes[group.id] = group.vlan_mode
  return { device_id: deviceId, ports, groups: groupModes }
}

/** Правило access: не более одного VLAN. Остаётся тот, что выбрал сервер (наименьший номер), а если
 * его в черновике нет (черновик разошёлся с БД) — первый из имеющихся, как у переключателя режима в форме. */
export function vlansForMode(current: string[], mode: VlanMode, serverKeep: string[]): string[] {
  if (mode !== 'access' || current.length <= 1) return current
  const keep = current.find((id) => serverKeep.includes(id)) ?? current[0]
  return [keep]
}

function setRowMode(row: InterfaceDraftRow, mode: VlanMode, serverKeep: string[]): InterfaceDraftRow {
  return { ...row, vlan_mode: mode, vlan_ids: vlansForMode(row.vlan_ids, mode, serverKeep) }
}

function setGroupMode(group: InterfaceGroupDraft, plan: CascadeGroupChange, mode: VlanMode): InterfaceGroupDraft {
  return { ...group, vlan_mode: mode, vlan_ids: vlansForMode(group.vlan_ids, mode, plan.vlans_after.map((v) => v.id)) }
}

/** Применяет к черновику формы изменения плана, помеченные deferred. Строки без id (ещё не
 * сохранённые) и группы без id в плане быть не могут и не затрагиваются. */
export function applyCascadeToDraft(
  rows: InterfaceDraftRow[],
  groups: InterfaceGroupDraft[],
  plan: VlanModeCascadePlan,
): { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[]; changedPorts: number } {
  const mode = plan.target_mode
  let nextRows = rows
  let nextGroups = groups
  const touched = new Set<string>()

  for (const change of plan.groups.filter((g) => g.deferred)) {
    const index = nextGroups.findIndex((g) => g.id === change.id)
    if (index < 0) continue
    const updated = setGroupMode(nextGroups[index], change, mode)
    nextGroups = nextGroups.map((g, i) => (i === index ? updated : g))
    // Члены группы по ЧЕРНОВИКУ: порт мог быть переведён в другую группу или выведен из неё без сохранения.
    nextRows = nextRows.map((row) => {
      if (row.group_key !== updated.key) return row
      if (row.id) touched.add(row.id)
      return applyGroupToRow(row, updated)
    })
    // Порты группы по БД, которых в группе черновика уже нет, всё равно должны получить режим.
    for (const member of change.ports) {
      const rowIndex = nextRows.findIndex((r) => r.id === member.id)
      if (rowIndex < 0 || nextRows[rowIndex].group_key === updated.key) continue
      touched.add(member.id)
      nextRows = nextRows.map((r, i) => (i === rowIndex ? setRowMode(r, mode, change.vlans_after.map((v) => v.id)) : r))
    }
  }

  for (const change of plan.ports.filter((p) => p.deferred)) {
    const rowIndex = nextRows.findIndex((r) => r.id === change.id)
    if (rowIndex < 0) continue
    touched.add(change.id)
    nextRows = nextRows.map((r, i) => (i === rowIndex ? setRowMode(r, mode, change.vlans_after.map((v) => v.id)) : r))
  }
  return { rows: nextRows, groups: nextGroups, changedPorts: touched.size }
}

/** Тривиальный план — один порт, без групп, без снимаемых VLAN и без изменений в форме: применяется
 * сразу, как раньше «Применить текущую конфигурацию», без отдельного окна подтверждения. */
export function isTrivialPlan(plan: VlanModeCascadePlan): boolean {
  return plan.totals.ports === 1 && plan.groups.length === 0 && plan.totals.dropped_vlans === 0 && plan.totals.deferred_ports === 0
}

export function modeLabel(mode: VlanMode): string {
  return mode === 'access' ? 'Access' : 'Trunk'
}
