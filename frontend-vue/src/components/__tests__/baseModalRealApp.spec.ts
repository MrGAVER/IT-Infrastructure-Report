// Раздел 5 ревью (frontend п. 4): один интеграционный тест «жизни» окон без Teleport-шва.
//
// Все остальные тесты окон идут через @vue/test-utils и настройку из src/__tests__/setup.ts: по умолчанию Teleport выключен, а у
// шести окон из списка имён — включён. Если бы боевой BaseModal снова начал зависеть от этой настройки или от имени окна-владельца
// (прежняя реализация, FE-05), тесты остались бы зелёными, потому что сами её и подставляют. Здесь окна монтируются настоящим
// приложением Vue (createApp): ни `config.global.provide`, ни миксина setup.ts, ни `realModalTeleport` — ровно то, что получит
// пользователь. Проверяется то, ради чего окно вынесено в <body>: вложенное окно выше родителя, Esc закрывает по одному, страница
// под окнами не прокручивается и освобождается после последнего.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref, type App, type VNodeChild } from 'vue'
import { hasOpenModal } from '../../composables/modalLayer'
import { readSource } from '../../__tests__/cssSource'
import BaseModal from '../BaseModal.vue'

const running: { app: App; container: HTMLElement }[] = []

function dialog(label: string, content: VNodeChild = null) {
  return h('div', { class: 'modal card', role: 'dialog', 'aria-label': label }, [h('button', { type: 'button' }, 'Кнопка'), content])
}

// Имена окон выбраны нарочно: «DevicePortsModal» — из списка шести имён, для которых setup.ts включает настоящий Teleport,
// «AnyOtherWindow» — не из списка. Для боевого кода имя ничего не значит, и оба окна обязаны вести себя одинаково.
const Inner = defineComponent({
  name: 'AnyOtherWindow',
  emits: ['close'],
  setup(_, { emit }) {
    return () => h(BaseModal, { onClose: () => emit('close') }, () => dialog('вложенное'))
  },
})

function outerWindow(onClose: () => void) {
  return defineComponent({
    name: 'DevicePortsModal',
    setup() {
      const innerOpen = ref(true)
      return () => h(BaseModal, { onClose }, () => dialog('родитель', innerOpen.value ? h(Inner, { onClose: () => (innerOpen.value = false) }) : null))
    },
  })
}

/** Настоящее приложение: createApp + mount, без обёрток @vue/test-utils и без глобальной настройки тестов. */
function openRealApp(onOuterClose: () => void) {
  const container = document.createElement('div')
  container.id = 'app'
  document.body.append(container)
  const Outer = outerWindow(onOuterClose)
  const app = createApp({ render: () => h(Outer) })
  app.mount(container)
  running.push({ app, container })
  return { app, container }
}

const overlays = () => Array.from(document.body.querySelectorAll<HTMLElement>('.modal-overlay'))
const depthOf = (label: string) => {
  const overlay = overlays().find((o) => o.querySelector('[role="dialog"]')?.getAttribute('aria-label') === label)
  return overlay ? Number(overlay.style.getPropertyValue('--modal-depth')) : undefined
}
const pressEscape = () => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))

afterEach(() => {
  while (running.length) {
    const { app, container } = running.pop()!
    app.unmount()
    container.remove()
  }
  document.body.innerHTML = ''
  document.body.style.cssText = ''
})

describe('окна в настоящем приложении (без Teleport-шва тестовой настройки)', () => {
  it('оба окна оказываются в <body>, а не внутри корня приложения — независимо от имени окна-владельца', () => {
    const { container } = openRealApp(() => {})
    expect(container.querySelector('.modal-overlay')).toBeNull()
    expect(overlays()).toHaveLength(2)
    for (const overlay of overlays()) expect(overlay.parentElement).toBe(document.body)
    expect(depthOf('родитель')).toBeDefined()
    expect(depthOf('вложенное')).toBeDefined()
  })

  it('порядок слоёв: вложенное окно на слой выше родителя — по стеку окон, а не по порядку в DOM', () => {
    openRealApp(() => {})
    expect(depthOf('родитель')).toBe(0)
    expect(depthOf('вложенное')).toBe(1)
    // z-index подложки — --z-modal плюс эта глубина (BaseModal.vue): число слоя берётся из стека, поэтому порядок подложек в <body>
    // (его определяет Teleport) на то, что окно выше родителя, не влияет. Обратный порядок в DOM проверяет BaseModal.spec.ts.
    expect(readSource('src/components/BaseModal.vue')).toContain('calc(var(--z-modal) + var(--modal-depth, 0))')
  })

  it('Esc закрывает по одному окну сверху вниз: сначала вложенное, затем родитель', async () => {
    const onOuterClose = vi.fn()
    openRealApp(onOuterClose)

    pressEscape()
    await nextTick()
    expect(depthOf('вложенное')).toBeUndefined() // вложенное окно закрылось
    expect(depthOf('родитель')).toBe(0) // родитель на месте
    expect(onOuterClose).not.toHaveBeenCalled()

    pressEscape()
    expect(onOuterClose).toHaveBeenCalledTimes(1)
  })

  it('страница под окнами не прокручивается, пока открыто хоть одно, и освобождается после закрытия последнего', async () => {
    const { app, container } = openRealApp(() => {})
    expect(document.body.style.overflow).toBe('hidden')
    expect(hasOpenModal.value).toBe(true)

    pressEscape() // закрылось вложенное — родитель ещё открыт
    await nextTick()
    expect(document.body.style.overflow).toBe('hidden')
    expect(hasOpenModal.value).toBe(true)

    app.unmount()
    running.splice(0, running.length)
    container.remove()
    expect(document.body.style.overflow).toBe('')
    expect(hasOpenModal.value).toBe(false)
    expect(overlays()).toHaveLength(0)
  })
})
