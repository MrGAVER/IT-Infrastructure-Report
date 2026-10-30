import { describe, it, expect } from 'vitest'
import {
  actionLabel,
  changeLines,
  optionLine,
  summaryLine,
  targetPort,
  plannedTargets,
  describeApply,
  describeRelation,
  describeRule,
  describeSide,
  draftFromRule,
  emptyRuleDraft,
  movedOrder,
  payloadFromDraft,
  validateRuleDraft,
  VLAN_POLICY_OPTIONS,
} from '../portSyncRules'
import type { PortSyncRule } from '../../api/types'

function rule(overrides: Partial<PortSyncRule> = {}): PortSyncRule {
  return {
    id: 'r1',
    code: null,
    builtin: false,
    modified: false,
    name: 'Правило',
    description: '',
    enabled: true,
    priority: 10,
    action: 'auto',
    target: { role: 'any', mode: 'any', vlans: 'any' },
    source: { role: 'any', mode: 'any', vlans: 'any' },
    relation: { role: 'any', mode: 'any', vlans: 'any' },
    apply: { role: false, mode: false, vlans: 'keep' },
    ...overrides,
  }
}

const emptyTrunk = rule({
  target: { role: 'any', mode: 'trunk', vlans: 'none' },
  source: { role: 'any', mode: 'trunk', vlans: 'set' },
  apply: { role: false, mode: true, vlans: 'copy' },
})

describe('portSyncRules utils — описание правила словами', () => {
  it('describeSide: перечисляет только заданные условия, «любое» пропускает', () => {
    expect(describeSide({ role: 'any', mode: 'any', vlans: 'any' })).toBe('')
    expect(describeSide({ role: 'any', mode: 'trunk', vlans: 'none' })).toBe('режим trunk, VLAN не назначены совсем')
    expect(describeSide({ role: 'data', mode: 'access', vlans: 'all' })).toBe('роль «Передача данных», режим access, назначены все VLAN')
    expect(describeSide({ role: 'any', mode: 'any', vlans: 'set' })).toContain('в том числе «Все VLAN»')
  })

  it('describeRelation: роли, режимы и наборы VLAN «совпадают» / «различаются»', () => {
    expect(describeRelation({ role: 'any', mode: 'any', vlans: 'any' })).toBe('')
    expect(describeRelation({ role: 'differs', mode: 'same', vlans: 'differs' })).toBe('роли различаются, режимы совпадают, наборы VLAN различаются')
  })

  it('describeApply: что берётся у соседа', () => {
    expect(describeApply({ apply: { role: true, mode: true, vlans: 'copy' } })).toBe('роль, режим, набор VLAN')
    expect(describeApply({ apply: { role: false, mode: true, vlans: 'adapt' } })).toBe('режим, VLAN приводятся к режиму')
    expect(describeApply({ apply: { role: false, mode: false, vlans: 'keep' } })).toBe('')
  })

  it('describeRule: правило про пустой trunk читается так, как его сформулировал пользователь', () => {
    expect(describeRule(emptyTrunk)).toBe(
      'Если порт: режим trunk, VLAN не назначены совсем; соседний порт: режим trunk, VLAN назначены (в том числе «Все VLAN») — порту применяется: режим, набор VLAN соседнего порта.',
    )
  })

  it('describeRule: ручное и игнорируемое правило, правило без условий', () => {
    expect(
      describeRule(rule({ action: 'manual', relation: { role: 'differs', mode: 'any', vlans: 'any' }, apply: { role: true, mode: false, vlans: 'keep' } })),
    ).toBe('Если роли различаются — расхождение требует решения человека (порту можно применить: роль соседа).')
    expect(describeRule(rule({ action: 'ignore', target: { role: 'management', mode: 'any', vlans: 'any' } }))).toBe(
      'Если порт: роль «Управление активами» — пару не согласовывать.',
    )
    expect(describeRule(rule())).toBe('Для любой пары портов подключения — порту применяется (изменения не заданы).')
  })

  it('actionLabel', () => {
    expect(actionLabel('auto')).toBe('Автоматически')
    expect(actionLabel('manual')).toBe('Решает человек')
    expect(actionLabel('ignore')).toBe('Не трогать')
  })
})

describe('portSyncRules utils — черновик и проверка', () => {
  it('новый черновик: автоматическое правило без условий, порядок не задан', () => {
    const draft = emptyRuleDraft()

    expect(draft).toMatchObject({ name: '', action: 'auto', enabled: true, priority: 0 })
    expect(draft.apply).toEqual({ role: false, mode: false, vlans: 'keep' })
  })

  it('draftFromRule копирует вложенные объекты — правка черновика не меняет правило в списке', () => {
    const original = rule({ ...emptyTrunk })
    const draft = draftFromRule(original)

    draft.target.mode = 'access'
    draft.apply.role = true

    expect(original.target.mode).toBe('trunk')
    expect(original.apply.role).toBe(false)
  })

  it.each([
    [{ name: '   ' }, 'Укажите название'],
    [{ name: 'x'.repeat(201) }, 'не длиннее 200'],
    [{ priority: 1.5 }, 'целое число'],
    [{ apply: { role: false, mode: false, vlans: 'adapt' as const } }, 'вместе со сменой режима'],
    [{ apply: { role: false, mode: false, vlans: 'keep' as const } }, 'должно что-то менять'],
  ])('validateRuleDraft отклоняет некорректный черновик (%j)', (patch, fragment) => {
    const error = validateRuleDraft({ ...draftFromRule(rule()), name: 'Имя', apply: { role: true, mode: false, vlans: 'keep' }, ...patch })

    expect(error).toContain(fragment)
  })

  it('validateRuleDraft пропускает корректные черновики, а manual и ignore могут ничего не менять', () => {
    const base = { ...draftFromRule(rule()), name: 'Имя' }

    expect(validateRuleDraft({ ...base, apply: { role: true, mode: false, vlans: 'keep' } })).toBeNull()
    expect(validateRuleDraft({ ...base, action: 'manual' })).toBeNull()
    expect(validateRuleDraft({ ...base, action: 'ignore' })).toBeNull()
  })

  it('payloadFromDraft: название без пробелов по краям; priority только по требованию', () => {
    const draft = { ...emptyRuleDraft(), name: '  Мой trunk ', priority: 7 }

    expect(payloadFromDraft(draft, { includePriority: false })).not.toHaveProperty('priority')
    expect(payloadFromDraft(draft, { includePriority: true })).toMatchObject({ name: 'Мой trunk', priority: 7 })
  })
})

describe('portSyncRules utils — порядок', () => {
  it('movedOrder сдвигает правило на одну позицию', () => {
    expect(movedOrder(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c'])
    expect(movedOrder(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b'])
  })

  it('на краях и для неизвестного id порядок не меняется (и это копия)', () => {
    const ids = ['a', 'b', 'c']
    expect(movedOrder(ids, 'a', -1)).toEqual(ids)
    expect(movedOrder(ids, 'c', 1)).toEqual(ids)
    expect(movedOrder(ids, 'zzz', 1)).toEqual(ids)
    expect(movedOrder(ids, 'a', -1)).not.toBe(ids)
  })
})

describe('portSyncRules utils — план согласования', () => {
  const port = (name: string, device: string) => ({
    interface_id: name,
    name,
    device_id: device,
    device_name: device,
    role: 'data' as const,
    mode: 'trunk' as const,
    vlans: [],
  })
  const item = { target: 'source' as const, source: port('Gi0/1', 'sw-1'), destination: port('Gi0/2', 'sw-2') }

  it('targetPort: порт, которому применяются изменения; без направления — null', () => {
    expect(targetPort(item)?.name).toBe('Gi0/1')
    expect(targetPort({ ...item, target: 'destination' })?.name).toBe('Gi0/2')
    expect(targetPort({ ...item, target: null })).toBeNull()
  })

  it('changeLines: роль, режим и VLAN построчно, VLAN диапазонами', () => {
    expect(
      changeLines({
        role: { from: 'management', to: 'data' },
        mode: { from: 'trunk', to: 'access' },
        vlans: { from: [], to: [10, 11, 12, 20], skipped: [] },
      }),
    ).toEqual(['роль: Управление активами → Передача данных', 'режим: trunk → access', 'VLAN: нет → 10–12, 20'])
    expect(changeLines(null)).toEqual([])
    expect(changeLines({ role: null, mode: null, vlans: null })).toEqual([])
  })

  it('changeLines: VLAN, которых нет у устройства, названы отдельно', () => {
    expect(changeLines({ role: null, mode: null, vlans: { from: [], to: [10, 20], skipped: [30] } })).toEqual([
      'VLAN: нет → 10, 20 (не назначены, нет у устройства: 30)',
    ])
  })

  it('optionLine: вариант ручного решения с портом и устройством', () => {
    expect(optionLine({ target: 'destination', changes: { role: 'data', mode: null, vlans: [10, 20] } }, item)).toBe(
      '«Gi0/2» (sw-2): роль → Передача данных, VLAN → 10, 20',
    )
    expect(optionLine({ target: 'source', changes: { role: null, mode: null, vlans: null } }, item)).toBe('«Gi0/1» (sw-1): изменений нет')
  })

  it('summaryLine: нулевые счётчики не показываются', () => {
    const base = { connections: 5, applicable: 2, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0 }
    expect(summaryLine(base)).toBe('проверено подключений: 5 · будет согласовано: 2')
    expect(summaryLine({ ...base, blocked: 1, manual: 2, none: 3 })).toBe(
      'проверено подключений: 5 · будет согласовано: 2 · нельзя применить: 1 · решает человек: 2 · без подходящего правила: 3',
    )
  })
})

describe('portSyncRules utils — политика «объединить»', () => {
  const union = rule({
    target: { role: 'any', mode: 'trunk', vlans: 'set' },
    source: { role: 'any', mode: 'trunk', vlans: 'set' },
    relation: { role: 'any', mode: 'any', vlans: 'differs' },
    apply: { role: false, mode: false, vlans: 'union' },
  })

  it('describeApply и describeRule: оба порта получают объединение, ни один VLAN не снимается', () => {
    expect(describeApply(union)).toBe('наборы VLAN объединяются на обоих портах')
    const sentence = describeRule(union)
    expect(sentence).toContain('оба порта получают объединение наборов VLAN')
    expect(sentence).toContain('наборы VLAN различаются')
    expect(sentence).not.toContain('порту применяется')
  })

  it('validateRuleDraft: «объединить» не сочетается со сменой роли или режима, а само по себе корректно', () => {
    const base = { ...emptyRuleDraft(), name: 'Объединять' }
    expect(validateRuleDraft({ ...base, apply: { role: false, mode: false, vlans: 'union' } })).toBeNull()
    expect(validateRuleDraft({ ...base, apply: { role: false, mode: true, vlans: 'union' } })).toContain('объединить')
    expect(validateRuleDraft({ ...base, apply: { role: true, mode: false, vlans: 'union' } })).toContain('объединить')
  })

  it('plannedTargets: оба порта из targets, у каждого свои изменения и причина запрета', () => {
    const view = (name: string) => ({
      interface_id: `if-${name}`,
      name,
      device_id: null,
      device_name: `dev-${name}`,
      role: 'data' as const,
      mode: 'trunk' as const,
      vlans: [],
    })
    const changes = { role: null, mode: null, vlans: { from: [10], to: [10, 20], skipped: [] } }
    const targets = plannedTargets({
      target: 'both',
      changes: null,
      source: view('a'),
      destination: view('b'),
      targets: [
        { target: 'source', changes, blocked: null },
        { target: 'destination', changes, blocked: 'Порт входит в группу' },
      ],
    })
    expect(targets.map((t) => [t.port.name, t.blocked])).toEqual([
      ['a', null],
      ['b', 'Порт входит в группу'],
    ])
  })

  it('plannedTargets: ответ старого формата (без targets) даёт единственный порт, без направления — пусто', () => {
    const view = (name: string) => ({
      interface_id: `if-${name}`,
      name,
      device_id: null,
      device_name: 'd',
      role: 'data' as const,
      mode: 'trunk' as const,
      vlans: [],
    })
    const changes = { role: null, mode: null, vlans: { from: [], to: [10], skipped: [] } }
    expect(plannedTargets({ target: 'destination', changes, source: view('a'), destination: view('b') }).map((t) => t.port.name)).toEqual(['b'])
    expect(plannedTargets({ target: null, changes: null, source: view('a'), destination: view('b') })).toEqual([])
    expect(targetPort({ target: 'both', source: view('a'), destination: view('b') })).toBeNull()
  })

  it('summaryLine: если портов больше, чем подключений, показываются оба числа', () => {
    const base = { connections: 4, applicable: 5, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0 }
    expect(summaryLine({ ...base, auto: 3 })).toBe('проверено подключений: 4 · будет согласовано: 3 (портов: 5)')
    expect(summaryLine({ ...base, applicable: 3, auto: 3 })).toBe('проверено подключений: 4 · будет согласовано: 3')
    expect(summaryLine(base)).toBe('проверено подключений: 4 · будет согласовано: 5') // без auto — как раньше
  })

  it('summaryLine: подключения, у которых расхождение останется, называются до подтверждения', () => {
    const base = { connections: 4, applicable: 4, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0 }
    expect(summaryLine({ ...base, partial: 2 })).toBe('проверено подключений: 4 · будет согласовано: 4 · расхождение останется у: 2')
    expect(summaryLine({ ...base, partial: 0 })).toBe('проверено подключений: 4 · будет согласовано: 4') // нулевой счётчик не показывается
    expect(summaryLine(base)).toBe('проверено подключений: 4 · будет согласовано: 4') // старый ответ без partial
  })
})

describe('portSyncRules utils — политика «все VLAN»', () => {
  const allVlans = rule({
    target: { role: 'any', mode: 'trunk', vlans: 'any' },
    source: { role: 'any', mode: 'trunk', vlans: 'all' },
    apply: { role: false, mode: false, vlans: 'all' },
  })

  it('политика есть в списке выбора', () => {
    expect(VLAN_POLICY_OPTIONS.map((o) => o.value)).toContain('all')
    expect(VLAN_POLICY_OPTIONS.find((o) => o.value === 'all')?.label).toContain('все VLAN')
  })

  it('describeApply и describeRule: порту назначаются все VLAN его устройства, а не VLAN соседа', () => {
    expect(describeApply(allVlans)).toBe('все VLAN его устройства («Все VLAN»)')
    const sentence = describeRule(allVlans)
    expect(sentence).toContain('соседний порт: режим trunk, назначены все VLAN')
    expect(sentence).toContain('порту применяется: все VLAN его устройства («Все VLAN»)')
    expect(sentence).not.toContain('соседнего порта') // «Все VLAN» не берутся у соседа — их определяет устройство порта
  })

  it('describeRule: «все VLAN» вместе с ролью и режимом — роль и режим берутся у соседа, «все VLAN» — нет', () => {
    const sentence = describeRule({ ...allVlans, apply: { role: true, mode: true, vlans: 'all' } })

    expect(sentence).toContain('порту применяется: роль, режим соседнего порта, все VLAN его устройства («Все VLAN»)')
  })

  it('describeRule: ручное правило с «все VLAN»', () => {
    const sentence = describeRule({ ...allVlans, action: 'manual' })

    expect(sentence).toContain('расхождение требует решения человека (порту можно применить: все VLAN его устройства («Все VLAN»))')
  })

  it('optionLine: вариант ручного решения «Все VLAN» без номеров', () => {
    const item = {
      source: { interface_id: 'a', name: 'Gi0/1', device_id: null, device_name: 'sw-1', role: 'data' as const, mode: 'trunk' as const, vlans: [10] },
      destination: { interface_id: 'b', name: 'Gi0/2', device_id: null, device_name: 'sw-2', role: 'data' as const, mode: 'trunk' as const, vlans: [10, 20] },
    }

    expect(optionLine({ target: 'source', changes: { role: null, mode: null, vlans: null, all_vlans: true } }, item)).toBe(
      '«Gi0/1» (sw-1): VLAN → все VLAN устройства',
    )
  })

  it('validateRuleDraft: правило с политикой «все VLAN» корректно и считается изменяющим для «Автоматически»', () => {
    const base = { ...emptyRuleDraft(), name: 'Все VLAN соседу', apply: { role: false, mode: false, vlans: 'all' as const } }

    expect(validateRuleDraft(base)).toBeNull()
  })
})
