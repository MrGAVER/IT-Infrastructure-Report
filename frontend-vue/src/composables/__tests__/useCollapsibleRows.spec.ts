import { describe, it, expect } from 'vitest'
import { nextTick, ref } from 'vue'
import { useCollapsibleRows } from '../useCollapsibleRows'

// limit: число — порог, 'off' — сворачивание выключено (порог undefined); по умолчанию 10.
// ('off', а не undefined: параметр по умолчанию подменил бы явно переданный undefined.)
function setup(initialRows: number, initialLimit: number | 'off' = 10) {
  const rows = ref(initialRows)
  const limit = ref<number | undefined>(initialLimit === 'off' ? undefined : initialLimit)
  const state = useCollapsibleRows(() => rows.value, () => limit.value)
  return { rows, limit, state }
}

describe('useCollapsibleRows', () => {
  it('свёрнуто только когда строк строго больше порога', () => {
    expect(setup(10).state.collapsed.value).toBe(false)
    expect(setup(11).state.collapsed.value).toBe(true)
    expect(setup(0).state.collapsed.value).toBe(false)
  })

  it('порог undefined — сворачивание выключено при любом количестве строк', () => {
    const { state } = setup(500, 'off')
    expect(state.exceedsLimit.value).toBe(false)
    expect(state.collapsed.value).toBe(false)
  })

  it('toggle и expand раскрывают список, повторный toggle сворачивает', () => {
    const { state } = setup(12)
    state.expand()
    expect(state.collapsed.value).toBe(false)
    state.toggle()
    expect(state.collapsed.value).toBe(true)
    state.toggle()
    expect(state.collapsed.value).toBe(false)
  })

  it('expandForAdd раскрывает список, когда после добавления строк станет больше порога, и не трогает его иначе', () => {
    const below = setup(5)
    below.state.expandForAdd()
    below.rows.value = 6
    expect(below.state.collapsed.value).toBe(false)

    const edge = setup(10)
    edge.state.expandForAdd() // добавление 11-й строки
    edge.rows.value = 11
    expect(edge.state.collapsed.value).toBe(false) // развёрнут, не свернулся под руками

    const already = setup(12)
    already.state.expandForAdd()
    expect(already.state.collapsed.value).toBe(false)
  })

  it('после снижения до порога ручное раскрытие сбрасывается: следующее превышение снова сворачивает', async () => {
    const { rows, state } = setup(12)
    state.expand()
    rows.value = 5
    await nextTick()
    rows.value = 15
    await nextTick()
    expect(state.collapsed.value).toBe(true)
  })

  it('смена порога пересчитывает состояние', () => {
    const { limit, state } = setup(12, 10)
    expect(state.collapsed.value).toBe(true)
    limit.value = 20
    expect(state.collapsed.value).toBe(false)
  })
})
