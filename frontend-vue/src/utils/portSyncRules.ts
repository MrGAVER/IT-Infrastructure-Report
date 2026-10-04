// Правила автоматического согласования данных порта — подписи, описание правила словами, черновик
// формы и проверка введённого. Чистые функции без Vue и сети: правила и их проверку выполняет
// сервер (backend/app/services/port_sync_rules.py), здесь только то, что нужно интерфейсу, чтобы
// показать правило человеку и не отправлять заведомо неверное.
import type {
  PortRole,
  PortSyncChanges,
  PortSyncOption,
  PortSyncPlanItem,
  PortSyncPortView,
  PortSyncAction,
  PortSyncCondition,
  PortSyncModeCondition,
  PortSyncOutcome,
  PortSyncRelation,
  PortSyncRoleCondition,
  PortSyncRule,
  PortSyncRuleInput,
  PortSyncVlanCondition,
  PortSyncVlanPolicy,
} from '../api/types'
import { formatVlans, roleLabel } from './portConfig'

export const ACTION_OPTIONS: { value: PortSyncAction; label: string; hint: string }[] = [
  { value: 'auto', label: 'Автоматически', hint: 'Направление определяют условия правила; изменения применяются после предпросмотра и подтверждения' },
  { value: 'manual', label: 'Решает человек', hint: 'Расхождение известного вида: какой порт менять, выбирает человек' },
  { value: 'ignore', label: 'Не трогать', hint: 'Пару не согласовывать: проверка правил ниже для неё не выполняется' },
]

export const ROLE_CONDITION_OPTIONS: { value: PortSyncRoleCondition; label: string }[] = [
  { value: 'any', label: 'любая' },
  { value: 'none', label: 'не задана' },
  { value: 'management', label: 'управление' },
  { value: 'data', label: 'передача данных' },
  { value: 'management_data', label: 'управление и передача данных' },
]

export const MODE_CONDITION_OPTIONS: { value: PortSyncModeCondition; label: string }[] = [
  { value: 'any', label: 'любой' },
  { value: 'trunk', label: 'trunk' },
  { value: 'access', label: 'access' },
]

export const VLAN_CONDITION_OPTIONS: { value: PortSyncVlanCondition; label: string }[] = [
  { value: 'any', label: 'любое' },
  { value: 'none', label: 'не назначены совсем' },
  { value: 'set', label: 'назначены (в том числе все)' },
  { value: 'all', label: 'назначены все (галочка «Все VLAN»)' },
]

export const RELATION_OPTIONS: { value: PortSyncRelation; label: string }[] = [
  { value: 'any', label: 'не важно' },
  { value: 'same', label: 'совпадают' },
  { value: 'differs', label: 'различаются' },
]

export const VLAN_POLICY_OPTIONS: { value: PortSyncVlanPolicy; label: string }[] = [
  { value: 'keep', label: 'не менять' },
  { value: 'copy', label: 'взять набор VLAN соседа' },
  { value: 'adapt', label: 'привести к режиму (в access — один VLAN)' },
]

export const OUTCOME_LABELS: Record<PortSyncOutcome, string> = {
  auto: 'Будет согласовано',
  blocked: 'Нельзя применить',
  manual: 'Решает человек',
  ignored: 'Исключено правилом',
  none: 'Правило не найдено',
  skipped: 'Вне согласования',
}

export function actionLabel(action: PortSyncAction): string {
  return ACTION_OPTIONS.find((o) => o.value === action)?.label ?? action
}

// --- описание правила словами -----------------------------------------------------------------

/** «режим trunk, VLAN не назначены совсем» — условия на один порт; пусто, если на порт ничего не задано. */
export function describeSide(side: PortSyncCondition<PortSyncVlanCondition>): string {
  const parts: string[] = []
  if (side.role !== 'any') parts.push(`роль «${roleLabel(side.role as PortRole)}»`)
  if (side.mode !== 'any') parts.push(`режим ${side.mode}`)
  if (side.vlans === 'none') parts.push('VLAN не назначены совсем')
  else if (side.vlans === 'set') parts.push('VLAN назначены (в том числе «Все VLAN»)')
  else if (side.vlans === 'all') parts.push('назначены все VLAN')
  return parts.join(', ')
}

export function describeRelation(relation: PortSyncRule['relation']): string {
  const parts: string[] = []
  const word = (value: PortSyncRelation) => (value === 'same' ? 'совпадают' : 'различаются')
  if (relation.role !== 'any') parts.push(`роли ${word(relation.role)}`)
  if (relation.mode !== 'any') parts.push(`режимы ${word(relation.mode)}`)
  if (relation.vlans !== 'any') parts.push(`наборы VLAN ${word(relation.vlans)}`)
  return parts.join(', ')
}

export function describeApply(rule: Pick<PortSyncRule, 'apply'>): string {
  const parts: string[] = []
  if (rule.apply.role) parts.push('роль')
  if (rule.apply.mode) parts.push('режим')
  if (rule.apply.vlans === 'copy') parts.push('набор VLAN')
  if (rule.apply.vlans === 'adapt') parts.push('VLAN приводятся к режиму')
  return parts.join(', ')
}

type Describable = Pick<PortSyncRule, 'action' | 'target' | 'source' | 'relation' | 'apply'>

/** Правило одним предложением: «Если порт: …, а соседний порт: …, и … — то порту применить: …». */
export function describeRule(rule: Describable): string {
  const condition: string[] = []
  const target = describeSide(rule.target)
  const source = describeSide(rule.source)
  const relation = describeRelation(rule.relation)
  if (target) condition.push(`порт: ${target}`)
  if (source) condition.push(`соседний порт: ${source}`)
  if (relation) condition.push(relation)
  const when = condition.length ? `Если ${condition.join('; ')}` : 'Для любой пары портов подключения'
  const apply = describeApply(rule)
  if (rule.action === 'ignore') return `${when} — пару не согласовывать.`
  if (rule.action === 'manual') return `${when} — расхождение требует решения человека${apply ? ` (порту можно применить: ${apply} соседа)` : ''}.`
  return `${when} — порту применяется${apply ? `: ${apply} соседнего порта` : ' (изменения не заданы)'}.`
}

// --- черновик формы ---------------------------------------------------------------------------

export type RuleDraft = PortSyncRuleInput

export function emptyRuleDraft(): RuleDraft {
  return {
    name: '',
    description: '',
    enabled: true,
    priority: 0,
    action: 'auto',
    target: { role: 'any', mode: 'any', vlans: 'any' },
    source: { role: 'any', mode: 'any', vlans: 'any' },
    relation: { role: 'any', mode: 'any', vlans: 'any' },
    apply: { role: false, mode: false, vlans: 'keep' },
  }
}

/** Копия правила для редактирования (вложенные объекты не разделяются с исходным). */
export function draftFromRule(rule: PortSyncRule): RuleDraft {
  return {
    name: rule.name,
    description: rule.description ?? '',
    enabled: rule.enabled,
    priority: rule.priority,
    action: rule.action,
    target: { ...rule.target },
    source: { ...rule.source },
    relation: { ...rule.relation },
    apply: { ...rule.apply },
  }
}

/** Проверка до отправки — те же правила, что на сервере; сервер всё равно перепроверяет. Возвращает
 * текст ошибки или null. */
export function validateRuleDraft(draft: RuleDraft): string | null {
  if (!draft.name.trim()) return 'Укажите название правила'
  if (draft.name.trim().length > 200) return 'Название правила не длиннее 200 символов'
  if (!Number.isInteger(draft.priority)) return 'Порядок проверки — целое число'
  if (draft.apply.vlans === 'adapt' && !draft.apply.mode) return 'Политика VLAN «привести к режиму» имеет смысл только вместе со сменой режима'
  if (draft.action === 'auto' && !draft.apply.role && !draft.apply.mode && draft.apply.vlans === 'keep') {
    return 'Правило с действием «Автоматически» должно что-то менять: роль, режим или VLAN'
  }
  return null
}

/** Тело запроса из черновика: название без пробелов по краям; priority у нового правила не
 * отправляется (сервер поставит его в конец списка). */
export function payloadFromDraft(draft: RuleDraft, { includePriority }: { includePriority: boolean }): Partial<PortSyncRuleInput> {
  const { priority, ...rest } = draft
  return { ...rest, name: draft.name.trim(), ...(includePriority ? { priority } : {}) }
}

/** Порядок id после перемещения правила на одну позицию (−1 вверх, +1 вниз); без изменений на краях. */
export function movedOrder(ids: readonly string[], id: string, delta: -1 | 1): string[] {
  const index = ids.indexOf(id)
  const target = index + delta
  if (index === -1 || target < 0 || target >= ids.length) return [...ids]
  const next = [...ids]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

// --- план согласования ------------------------------------------------------------------------

/** Порт подключения, которому применяются изменения (для auto и blocked); null, если направление не определено. */
export function targetPort(item: Pick<PortSyncPlanItem, 'target' | 'source' | 'destination'>): PortSyncPortView | null {
  if (item.target === 'source') return item.source
  if (item.target === 'destination') return item.destination
  return null
}

/** Изменения порта построчно: «роль: Управление активами → Передача данных», «режим: trunk → access»,
 * «VLAN: нет → 10, 20 (не назначены, нет у устройства: 30)». */
export function changeLines(changes: PortSyncChanges | null): string[] {
  if (!changes) return []
  const lines: string[] = []
  if (changes.role) lines.push(`роль: ${roleLabel(changes.role.from)} → ${roleLabel(changes.role.to)}`)
  if (changes.mode) lines.push(`режим: ${changes.mode.from} → ${changes.mode.to}`)
  if (changes.vlans) {
    const skipped = changes.vlans.skipped.length ? ` (не назначены, нет у устройства: ${formatVlans(changes.vlans.skipped)})` : ''
    const to = changes.vlans.skipped.length && changes.vlans.from.join() === changes.vlans.to.join() ? 'без изменений' : formatVlans(changes.vlans.to)
    lines.push(`VLAN: ${formatVlans(changes.vlans.from)} → ${to}${skipped}`)
  }
  return lines
}

/** Вариант ручного решения: «порту Gi0/1: роль → Передача данных, режим → trunk, VLAN → 10, 20». */
export function optionLine(option: PortSyncOption, item: Pick<PortSyncPlanItem, 'source' | 'destination'>): string {
  const port = option.target === 'source' ? item.source : item.destination
  const parts: string[] = []
  if (option.changes.role) parts.push(`роль → ${roleLabel(option.changes.role)}`)
  if (option.changes.mode) parts.push(`режим → ${option.changes.mode}`)
  if (option.changes.vlans) parts.push(`VLAN → ${formatVlans(option.changes.vlans)}`)
  return `«${port.name}» (${port.device_name}): ${parts.join(', ') || 'изменений нет'}`
}

/** Сводка плана одной строкой — только ненулевые счётчики. */
export function summaryLine(summary: {
  connections: number; applicable: number; blocked: number; manual: number; ignored: number; none: number; skipped: number
}): string {
  const parts = [`проверено подключений: ${summary.connections}`, `будет согласовано: ${summary.applicable}`]
  if (summary.blocked) parts.push(`нельзя применить: ${summary.blocked}`)
  if (summary.manual) parts.push(`решает человек: ${summary.manual}`)
  if (summary.ignored) parts.push(`исключено правилами: ${summary.ignored}`)
  if (summary.none) parts.push(`без подходящего правила: ${summary.none}`)
  if (summary.skipped) parts.push(`вне согласования: ${summary.skipped}`)
  return parts.join(' · ')
}
