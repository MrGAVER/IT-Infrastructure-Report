import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ScrollableTableWrap from '../ScrollableTableWrap.vue'
import { readStyles } from '../../__tests__/cssSource'

// UI-06 (ревью merge/review-2158-executors): на телефоне видны 3 колонки из 9, подсказки о прокрутке нет.
// jsdom не считает раскладку, поэтому размеры и прокрутка подменяются на элементе.

interface Metrics {
  scrollWidth: number
  clientWidth: number
  scrollLeft: number
}

function setMetrics(el: Element, metrics: Metrics) {
  for (const [name, value] of Object.entries(metrics)) Object.defineProperty(el, name, { value, configurable: true, writable: true })
}

function mountWrap(attrs: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  return mount(ScrollableTableWrap, { props, attrs, slots: { default: '<table><tbody><tr><td>x</td></tr></tbody></table>' } })
}

async function scrollTo(wrapper: ReturnType<typeof mountWrap>, metrics: Metrics) {
  setMetrics(wrapper.element, metrics)
  await wrapper.trigger('scroll')
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ScrollableTableWrap.vue', () => {
  it('таблица помещается целиком — подсказки нет и в порядок фокуса контейнер не попадает', async () => {
    const wrapper = mountWrap()
    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 880, scrollLeft: 0 })

    expect(wrapper.classes()).not.toContain('shade-left')
    expect(wrapper.classes()).not.toContain('shade-right')
    expect(wrapper.attributes('tabindex')).toBeUndefined()
  })

  it('есть непоказанные колонки справа (начало таблицы) — затухает только правый край, контейнер фокусируется', async () => {
    const wrapper = mountWrap()
    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 350, scrollLeft: 0 })

    expect(wrapper.classes()).toContain('shade-right')
    expect(wrapper.classes()).not.toContain('shade-left')
    expect(wrapper.attributes('tabindex')).toBe('0')
  })

  it('прокручено до середины — затухают оба края', async () => {
    const wrapper = mountWrap()
    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 350, scrollLeft: 200 })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['shade-left', 'shade-right']))
  })

  it('прокручено до конца — остаётся только левый край; недокрутка меньше пикселя не считается остатком', async () => {
    const wrapper = mountWrap()

    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 350, scrollLeft: 530 })
    expect(wrapper.classes()).toContain('shade-left')
    expect(wrapper.classes()).not.toContain('shade-right')

    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 350, scrollLeft: 529.6 })
    expect(wrapper.classes()).not.toContain('shade-right')
  })

  it('это именно область прокрутки: role=region с подписью (по умолчанию «Таблица», иначе из label)', () => {
    expect(mountWrap().attributes('role')).toBe('region')
    expect(mountWrap().attributes('aria-label')).toBe('Таблица')
    expect(mountWrap({}, { label: 'Список устройств' }).attributes('aria-label')).toBe('Список устройств')
  })

  it('класс родителя (stale у подключений) попадает на корневой элемент, а .table-wrap остаётся', () => {
    const wrapper = mountWrap({ class: 'stale' })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['table-wrap', 'stale']))
  })

  it('при перерисовке (смена содержимого) подсказка пересчитывается', async () => {
    const wrapper = mountWrap()
    await scrollTo(wrapper, { scrollWidth: 880, clientWidth: 880, scrollLeft: 0 })
    expect(wrapper.classes()).not.toContain('shade-right')

    setMetrics(wrapper.element, { scrollWidth: 1200, clientWidth: 880, scrollLeft: 0 })
    await wrapper.setProps({ label: 'Другая таблица' })

    expect(wrapper.classes()).toContain('shade-right')
  })

  describe('ResizeObserver', () => {
    function stubResizeObserver() {
      const instances: Array<{ callback: () => void; observed: Element[]; disconnect: ReturnType<typeof vi.fn> }> = []
      class FakeResizeObserver {
        callback: () => void
        observed: Element[] = []
        disconnect = vi.fn()
        constructor(callback: () => void) {
          this.callback = callback
          instances.push(this)
        }
        observe(el: Element) {
          this.observed.push(el)
        }
      }
      vi.stubGlobal('ResizeObserver', FakeResizeObserver)
      return instances
    }

    it('следит за контейнером и таблицей внутри и пересчитывает подсказку при смене размеров (поворот телефона)', () => {
      const instances = stubResizeObserver()
      const wrapper = mountWrap()

      expect(instances).toHaveLength(1)
      expect(instances[0].observed).toEqual([wrapper.element, wrapper.element.firstElementChild])

      setMetrics(wrapper.element, { scrollWidth: 880, clientWidth: 350, scrollLeft: 0 })
      instances[0].callback()
      return wrapper.vm.$nextTick().then(() => {
        expect(wrapper.classes()).toContain('shade-right')
      })
    })

    it('при размонтировании наблюдатель отключается', () => {
      const instances = stubResizeObserver()
      const wrapper = mountWrap()

      wrapper.unmount()

      expect(instances[0].disconnect).toHaveBeenCalledTimes(1)
    })
  })
})

describe('ScrollableTableWrap.vue — стили', () => {
  const styles = readStyles('src/components/ScrollableTableWrap.vue')

  it('прокрутка по горизонтали включена, подсказка — маска на нужном краю (с префиксом для Safari)', () => {
    expect(styles).toMatch(/\.table-wrap \{\s*overflow-x: auto;/)
    expect(styles).toMatch(/\.table-wrap\.shade-right \{[^}]*-webkit-mask-image: linear-gradient\(to right,[^}]*mask-image: linear-gradient\(to right,/)
    expect(styles).toMatch(/\.table-wrap\.shade-left \{[^}]*mask-image: linear-gradient\(to left,/)
    expect(styles).toMatch(/\.table-wrap\.shade-left\.shade-right \{[^}]*transparent, #000 28px/)
  })
})
