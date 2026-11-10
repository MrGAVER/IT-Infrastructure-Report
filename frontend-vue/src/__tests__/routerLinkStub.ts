// B-07: тестовые замены <router-link> и <router-view> для спеков, которые монтируют компонент без vue-router.
//
// Без неё каждый такой спек сыпал `[Vue warn]: Failed to resolve component: router-link` (около 1100 предупреждений за прогон: сообщения
// маскировали настоящие проблемы), а `<router-link>` рисовался неизвестным элементом. Заглушка рисует обычную ссылку с href — тест может
// проверять, куда ведёт пункт меню, как и с настоящим роутером. Регистрируется она в setup.ts лениво и только если приложение само не
// получило настоящий RouterLink (спеки с createRouter() не затрагиваются).
import { defineComponent, h, type PropType } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

/** href для `to`: строка как есть; для объекта — path (+ query/hash), имя маршрута без роутера разрешить нечем — тогда '#'. */
export function hrefOf(to: RouteLocationRaw): string {
  if (typeof to === 'string') return to
  const target = to as { path?: string; query?: Record<string, unknown>; hash?: string }
  if (!target.path) return '#'
  const query = target.query ? new URLSearchParams(Object.entries(target.query).map(([k, v]) => [k, String(v)])).toString() : ''
  return `${target.path}${query ? `?${query}` : ''}${target.hash ?? ''}`
}

export const RouterLinkTestStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object] as PropType<RouteLocationRaw>, required: true } },
  setup(props, { slots }) {
    return () => h('a', { href: hrefOf(props.to) }, slots.default?.())
  },
})

/** Место для вложенного маршрута: тестам оболочки содержимое страницы не нужно, достаточно того, что компонент существует. */
export const RouterViewTestStub = defineComponent({
  name: 'RouterView',
  setup: () => () => null,
})
