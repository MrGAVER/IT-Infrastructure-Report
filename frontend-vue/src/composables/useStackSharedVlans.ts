// Общие VLAN стеков для дашборда «Стеки устройств»: подгружаются лениво — только для раскрытых строк на текущей странице,
// по одному запросу GET /device-stacks/{id}/vlans на стек, и кэшируются до сброса. Так экран не делает N запросов при
// открытии, а раскрытие всех строк («Развернуть все») тянет данные только страницы, которая на экране.
import { ref, watch } from 'vue'
import { api } from '../api/client'
import type { DeviceStackVlans, StackVlanRow } from '../api/types'

export type StackVlansState = { status: 'loading' } | { status: 'ready'; items: StackVlanRow[] } | { status: 'error'; message: string }

/**
 * @param neededStackIds возвращает id стеков, чьи общие VLAN сейчас показаны (раскрытые строки текущей страницы); при изменении
 *   результата недостающие загружаются сами.
 */
export function useStackSharedVlans(neededStackIds: () => readonly string[]) {
  const states = ref(new Map<string, StackVlansState>())
  // Номер «поколения» кэша: ответ, пришедший после invalidate(), относится к уже сброшенному кэшу и отбрасывается — иначе он
  // перезаписал бы более свежую загрузку, начатую после сброса.
  const generation = ref(0)

  async function load(stackId: string) {
    if (states.value.has(stackId)) return
    const startedIn = generation.value
    states.value.set(stackId, { status: 'loading' })
    try {
      const res = await api.get<DeviceStackVlans>(`/device-stacks/${stackId}/vlans`)
      if (startedIn !== generation.value) return
      states.value.set(stackId, { status: 'ready', items: res.items ?? [] })
    } catch (err) {
      if (startedIn !== generation.value) return
      states.value.set(stackId, { status: 'error', message: err instanceof Error ? err.message : 'Не удалось загрузить общие VLAN стека' })
    }
  }

  /** Состояние стека; undefined — данные ещё не запрашивались (строка не раскрывалась). */
  function stateOf(stackId: string): StackVlansState | undefined {
    return states.value.get(stackId)
  }

  /** Сбросить всё: общие VLAN могли измениться (окно стека, «Обновить»); раскрытые строки на экране загрузятся заново. */
  function invalidate() {
    generation.value++
    states.value.clear()
  }

  /** Повторить загрузку одного стека после ошибки. */
  function retry(stackId: string) {
    states.value.delete(stackId)
    void load(stackId)
  }

  watch(
    () => [generation.value, neededStackIds().join('\u0000')],
    () => {
      for (const id of neededStackIds()) void load(id)
    },
    { immediate: true },
  )

  return { stateOf, invalidate, retry }
}
