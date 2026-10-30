// Перенос изменений каскадной смены режима порта на редактируемое устройство (см.
// api/vlanModeCascade.ts и backend/app/services/vlan_mode_cascade.py).
//
// Сервер не пишет порты и группы устройства с открытой формой — форма сохраняется целиком и
// перезаписала бы запись в обход неё. Он отдаёт их в плане с пометкой deferred, а здесь те же
// изменения вносятся в ЧЕРНОВИК формы: сохранятся вместе с ней (кнопка «Сохранить»).
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../api/types'
import type { CascadeGroupChange, EditedDeviceState, VlanMode, VlanModeCascadePlan } from '../api/vlanModeCascade'
import { applyGroupToRow } from './interfaceGroups'

/** Состояние формы для запросов каскада: режим, группа, VLAN и имя сохранённых портов и всех групп
 * (в т.ч. новых — по временному ключу) ИЗ ЧЕРНОВИКА. null — форма без устройства (создание). */
export function buildEditedState(deviceId: string | null | undefined, rows: InterfaceDraftRow[], groups: InterfaceGroupDraft[]): EditedDeviceState | null {
  if (!deviceId) return null
  const ports: EditedDeviceState['ports'] = {}
  for (const row of rows) {
    if (row.id) ports[row.id] = { name: row.name, mode: row.vlan_mode, group: row.group_key || null, vlan_ids: [...row.vlan_ids] }
  }
  const groupStates: EditedDeviceState['groups'] = {}
  for (const group of groups) groupStates[group.key] = { name: group.name, mode: group.vlan_mode, vlan_ids: [...group.vlan_ids] }
  return { device_id: deviceId, ports, groups: groupStates }
}

/** Правило access: не более одного VLAN. Остаётся тот, что выбрал сервер (наименьший номер), а если
 * его в черновике нет (черновик разошёлся с БД) — первый из имеющихся, как у переключателя режима в форме. */
export function vlansForMode(current: string[], mode: VlanMode, serverKeep: string[]): string[] {
  if (mode !== 'access' || current.length <= 1) return current
  const keep = current.find((id) => serverKeep.includes(id)) ?? current[0]
  return [keep]
}

function setRowMode(row: InterfaceDraftRow, mode: VlanMode, serverKeep: string[]): InterfaceDraftRow {
  // В access «Все VLAN» невозможно: признак снимается вместе со сменой режима (сервер делает то же).
  return { ...row, vlan_mode: mode, vlan_ids: vlansForMode(row.vlan_ids, mode, serverKeep), all_vlans: mode === 'access' ? false : row.all_vlans === true }
}

function setGroupMode(group: InterfaceGroupDraft, plan: CascadeGroupChange, mode: VlanMode): InterfaceGroupDraft {
  return {
    ...group,
    vlan_mode: mode,
    vlan_ids: vlansForMode(
      group.vlan_ids,
      mode,
      plan.vlans_after.map((v) => v.id),
    ),
    all_vlans: mode === 'access' ? false : group.all_vlans === true,
  }
}

/** Применяет к черновику формы изменения плана, помеченные deferred. Группа в плане задана ключом (у
 * сохранённой группы он равен id, у новой — временный). Строки без id (ещё не сохранённые) в плане быть
 * не могут, но получают режим группы, если входят в неё в черновике. */
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
    const index = nextGroups.findIndex((g) => g.key === change.id)
    if (index < 0) continue
    const updated = setGroupMode(nextGroups[index], change, mode)
    nextGroups = nextGroups.map((g, i) => (i === index ? updated : g))
    // Члены группы — по ЧЕРНОВИКУ (сервер считал состав по нему же); строки без id тоже получают режим группы.
    nextRows = nextRows.map((row) => {
      if (row.group_key !== updated.key) return row
      if (row.id) touched.add(row.id)
      return applyGroupToRow(row, updated)
    })
  }

  for (const change of plan.ports.filter((p) => p.deferred)) {
    const rowIndex = nextRows.findIndex((r) => r.id === change.id)
    if (rowIndex < 0) continue
    touched.add(change.id)
    nextRows = nextRows.map((r, i) =>
      i === rowIndex
        ? setRowMode(
            r,
            mode,
            change.vlans_after.map((v) => v.id),
          )
        : r,
    )
  }
  return { rows: nextRows, groups: nextGroups, changedPorts: touched.size }
}

/** Тривиальный план — один порт без групп и без снимаемых VLAN: применяется сразу, без отдельного окна
 * подтверждения (как раньше «Применить текущую конфигурацию»). Если этот порт — порт самой формы, он
 * просто меняется в черновике. */
export function isTrivialPlan(plan: VlanModeCascadePlan): boolean {
  return plan.totals.ports === 1 && plan.groups.length === 0 && plan.totals.dropped_vlans === 0
}

/** План меняет только порт самой формы (один порт, без групп и снимаемых VLAN, на других устройствах
 * ничего): достаточно правки черновика, запрос на запись не нужен. */
export function isFormOnlyPlan(plan: VlanModeCascadePlan): boolean {
  return isTrivialPlan(plan) && plan.totals.immediate_ports === 0
}

export function modeLabel(mode: VlanMode): string {
  return mode === 'access' ? 'Access' : 'Trunk'
}
