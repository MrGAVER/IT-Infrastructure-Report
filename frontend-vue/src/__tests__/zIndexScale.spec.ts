// Хвост F-03 (код-ревью main): шкала слоёв. Числовые z-index (20 / 25 / 30 / 80 / 85 / 100) были разбросаны по десяти файлам, и порядок
// слоёв — что поверх чего — нигде не читался целиком. Теперь все они — токены --z-* в styles/theme.css. Этот тест не даёт вернуть
// число в стили (оно появилось бы снова при первом же копировании компонента) и следит, что порядок слоёв не сломан.
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { readSource } from './cssSource'

const SRC = 'src'
// Локальные слои внутри одного компонента (0, 1, 2…) допустимы: они не конкурируют с остальным приложением.
const LOCAL_Z_INDEX_LIMIT = 10

function walk(dir: string): string[] {
  return readdirSync(path.resolve(process.cwd(), dir), { withFileTypes: true }).flatMap((entry) => {
    const full = `${dir}/${entry.name}`
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : walk(full)
    return [full]
  })
}

const styled = walk(SRC).filter((file) => file.endsWith('.vue') || file.endsWith('.css'))

/** Токены шкалы из theme.css: имя без --z- → значение. */
function tokens(): Map<string, number> {
  const theme = readSource(`${SRC}/styles/theme.css`)
  return new Map(Array.from(theme.matchAll(/--z-([a-z-]+):\s*(\d+)/g), (match) => [match[1], Number(match[2])]))
}

describe('шкала слоёв: z-index только через токены', () => {
  it('в стилях нет числового z-index от 10 и выше', () => {
    const offenders = styled.flatMap((file) =>
      Array.from(readSource(file).matchAll(/z-index:\s*(\d+)/g))
        .filter((match) => Number(match[1]) >= LOCAL_Z_INDEX_LIMIT)
        .map((match) => `${file}: z-index: ${match[1]}`),
    )
    expect(offenders, 'используйте токен --z-* из styles/theme.css').toEqual([])
  })

  it('каждый var(--z-…) в стилях объявлен в theme.css', () => {
    const declared = tokens()
    const unknown = styled.flatMap((file) =>
      Array.from(readSource(file).matchAll(/var\(--z-([a-z-]+)\)/g))
        .filter((match) => !declared.has(match[1]))
        .map((match) => `${file}: --z-${match[1]}`),
    )
    expect(unknown).toEqual([])
  })

  it('порядок слоёв: страница < меню < окна < подсказка «?» < список выбора < подсказка у текста < уведомления', () => {
    const z = tokens()
    const order = ['raised', 'sidebar-backdrop', 'sidebar', 'modal', 'help-tip', 'popover', 'tooltip', 'toast']
    const values = order.map((name) => z.get(name))
    expect(values.every((value) => value !== undefined)).toBe(true)
    expect(values, 'каждый следующий слой строго выше предыдущего').toEqual([...(values as number[])].sort((a, b) => a - b))
    expect(new Set(values).size).toBe(order.length)
  })

  it('меню пользователя лежит под окнами: окно всегда поверх', () => {
    const z = tokens()
    expect(z.get('menu')!).toBeLessThan(z.get('modal')!)
  })

  it('найдены все файлы со стилями — иначе проверки выше ничего не охватывают', () => {
    expect(styled.length).toBeGreaterThan(100)
  })
})
