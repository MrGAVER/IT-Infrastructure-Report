// UI-05 (ревью 2.158.0): AppShell публикует фактическую высоту липкой шапки в --topbar-h, чтобы экраны на всю высоту окна
// вычитали её, а не «магические» 96 px.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { readStyles, ruleBody, declaration } from '../../__tests__/cssSource'

vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'dashboard', meta: {} }) }))

import AppShell from '../AppShell.vue'

let observerCallback: (() => void) | null = null
let disconnected = false
let topbarHeight = 62.4

class FakeResizeObserver {
  constructor(cb: () => void) {
    observerCallback = cb
  }
  observe() {}
  disconnect() {
    disconnected = true
  }
}

const stubs = {
  Sidebar: true,
  ToastHost: true,
  PortSyncPlanHost: true,
  'router-view': true,
  Topbar: { template: '<div class="topbar" />' },
}

function mountShell() {
  const proto = HTMLElement.prototype
  vi.spyOn(proto, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return { height: this.classList.contains('topbar') ? topbarHeight : 0 } as DOMRect
  })
  return mount(AppShell, { global: { stubs } })
}

beforeEach(() => {
  observerCallback = null
  disconnected = false
  topbarHeight = 62.4
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('UI-05: AppShell — --topbar-h', () => {
  it('после монтирования высота шапки (округлённая вверх) лежит в --topbar-h на корне оболочки', () => {
    const wrapper = mountShell()
    expect((wrapper.get('.app-shell').element as HTMLElement).style.getPropertyValue('--topbar-h')).toBe('63px')
  })

  it('следует за шапкой: перенос заголовка меняет высоту — значение обновляется', () => {
    const wrapper = mountShell()
    topbarHeight = 105
    observerCallback!()
    expect((wrapper.get('.app-shell').element as HTMLElement).style.getPropertyValue('--topbar-h')).toBe('105px')
  })

  it('наблюдатель снимается при размонтировании, без ResizeObserver (jsdom) всё равно работает', () => {
    mountShell().unmount()
    expect(disconnected).toBe(true)

    vi.stubGlobal('ResizeObserver', undefined)
    const wrapper = mountShell()
    expect((wrapper.get('.app-shell').element as HTMLElement).style.getPropertyValue('--topbar-h')).toBe('63px')
  })

  it('отступы контента вынесены в переменные, которые вычитает экран диаграммы, и держатся на dvh', () => {
    const css = readStyles('src/layout/AppShell.vue')
    const shell = ruleBody(css, '.app-shell')
    expect(shell).toContain('--content-pad-top: 18px')
    expect(shell).toContain('--content-pad-bottom: 32px')
    expect(shell).toContain('min-height: 100dvh')
    expect(declaration(ruleBody(css, '.content'), 'padding')).toBe('var(--content-pad-top) 20px var(--content-pad-bottom)')
  })
})
