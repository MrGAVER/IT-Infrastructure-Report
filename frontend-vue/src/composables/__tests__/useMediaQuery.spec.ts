import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { useMediaQuery } from '../useMediaQuery'

type Listener = (event: { matches: boolean }) => void

function stubMatchMedia(initial: boolean) {
  const listeners = new Set<Listener>()
  const list = {
    matches: initial,
    addEventListener: vi.fn((_: string, cb: Listener) => listeners.add(cb)),
    removeEventListener: vi.fn((_: string, cb: Listener) => listeners.delete(cb)),
  }
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => list),
  )
  return { list, emit: (matches: boolean) => listeners.forEach((cb) => cb({ matches })), listeners }
}

function mountProbe(query: string) {
  let result!: ReturnType<typeof useMediaQuery>
  const wrapper = mount(
    defineComponent({
      setup() {
        result = useMediaQuery(query)
        return () => h('div')
      },
    }),
  )
  return { wrapper, result: () => result.value }
}

afterEach(() => vi.unstubAllGlobals())

describe('UI-02: useMediaQuery', () => {
  it('отдаёт текущее значение и реагирует на смену ширины окна', () => {
    const media = stubMatchMedia(true)
    const { result } = mountProbe('(max-width: 760px)')
    expect(result()).toBe(true)
    media.emit(false)
    expect(result()).toBe(false)
  })

  it('отписывается при размонтировании компонента', () => {
    const media = stubMatchMedia(false)
    const { wrapper } = mountProbe('(max-width: 760px)')
    expect(media.listeners.size).toBe(1)
    wrapper.unmount()
    expect(media.listeners.size).toBe(0)
  })

  it('без window.matchMedia (jsdom) возвращает false и не падает', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(mountProbe('(max-width: 760px)').result()).toBe(false)
  })
})
