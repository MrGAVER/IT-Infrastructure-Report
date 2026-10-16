// Маршрут «Другие справочники»: ?catalog= передаётся экрану пропом (так дашборд открывает «Программные активы»).
import { describe, it, expect } from 'vitest'
import { createMemoryHistory, createRouter, type RouteLocationNormalized } from 'vue-router'
import { routes } from '../index'

const router = createRouter({ history: createMemoryHistory(), routes })

/** Пропы, которые маршрут передаст экрану для данного адреса (то же, что делает RouterView). Функции пропов нужен
 * только query, поэтому тип параметра сужен: результат resolve() — не «нормализованный» маршрут для компилятора. */
function propsFor(location: string): Record<string, unknown> {
  const resolved = router.resolve(location)
  const props = resolved.matched[0].props.default
  expect(typeof props).toBe('function')
  return (props as (route: Pick<RouteLocationNormalized, 'query'>) => Record<string, unknown>)(resolved)
}

describe('маршрут /other-catalogs', () => {
  it('?catalog=software-assets передаётся проп catalog', () => {
    expect(propsFor('/other-catalogs?catalog=software-assets')).toEqual({ catalog: 'software-assets' })
  })

  it('без параметра проп не задан — экран откроет первый справочник', () => {
    expect(propsFor('/other-catalogs')).toEqual({ catalog: undefined })
  })

  it('повторяющийся параметр (массив) не принимается за ключ справочника', () => {
    expect(propsFor('/other-catalogs?catalog=a&catalog=b')).toEqual({ catalog: undefined })
  })
})
