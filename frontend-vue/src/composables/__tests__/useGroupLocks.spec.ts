import { describe, expect, it } from 'vitest'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { useGroupLocks } from '../useGroupLocks'

describe('useGroupLocks', () => {
  const group = { ...emptyGroup('Магистраль'), key: 'g1', vlan_mode: 'trunk' as const }

  it('находит группу порта по group_key; у порта вне групп ничего не заблокировано', () => {
    const { rowGroup, rowManaged } = useGroupLocks(() => [group])
    expect(rowGroup(makeRow({ group_key: 'g1' }))).toBe(group)
    expect(rowGroup(makeRow())).toBeUndefined()
    expect(rowManaged(makeRow())).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
  })

  it('управляемые группой поля определяются по её заполненным параметрам', () => {
    const { rowManaged } = useGroupLocks(() => [group])
    expect(rowManaged(makeRow({ group_key: 'g1' }))).toMatchObject({ vlan: true, ip: false })
  })

  it('подсказка называет поле и группу; список групп читается заново при каждом вызове', () => {
    let groups = [group]
    const { groupLockNote } = useGroupLocks(() => groups)
    expect(groupLockNote(makeRow({ group_key: 'g1' }), 'Режим порта')).toBe('Режим порта задан группой «Магистраль» — измените в группе или выведите порт из группы.')
    groups = []
    expect(groupLockNote(makeRow({ group_key: 'g1' }), 'Режим порта')).toContain('группой «»')
  })
})
