// UI-04 (ревью 2.158.0) и F-01…F-03 (код-ревью main): структурная проверка ВСЕХ модальных окон приложения. Новая модалка, которая
// сама рисует подложку, забыла BaseModal (а с ним Esc, фокус, блокировку прокрутки) или не назвала диалог, не пройдёт этот тест —
// без него правки по 34 файлам вернулись бы по одному при первом же копировании формы.
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { declaration, readSource, readStyles, ruleBody } from '../../__tests__/cssSource'

const SRC = 'src'

function walk(dir: string): string[] {
  return readdirSync(path.resolve(process.cwd(), dir), { withFileTypes: true }).flatMap((entry) => {
    const full = `${dir}/${entry.name}`
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : walk(full)
    return [full]
  })
}

const sourceFiles = walk(SRC).filter((file) => file.endsWith('.vue') || file.endsWith('.css'))
const modalFiles = sourceFiles.filter((file) => file.endsWith('.vue') && file !== `${SRC}/components/BaseModal.vue` && /<BaseModal\b/.test(readSource(file)))

function template(file: string): string {
  const source = readSource(file)
  const end = source.indexOf('<style')
  return source.slice(source.indexOf('<template>'), end === -1 ? undefined : end)
}

describe('модальные окна: общая основа BaseModal', () => {
  it('найдены все модалки (34 файла) — иначе проверки ниже ничего не охватывают', () => {
    expect(modalFiles.length).toBeGreaterThanOrEqual(34)
  })

  it('ни один файл не рисует подложку сам: класса overlay и его стилей в приложении нет', () => {
    const offenders = sourceFiles.filter((file) => /class="overlay\b|^\s*\.overlay\b/m.test(readSource(file)))
    expect(offenders).toEqual([])
  })

  it('.modal-overlay объявлен ровно в одном месте — BaseModal.vue', () => {
    const owners = sourceFiles.filter((file) => /^\s*\.modal-overlay\s*[{,]/m.test(readSource(file)))
    expect(owners).toEqual([`${SRC}/components/BaseModal.vue`])
  })

  it('слой окон задаётся токеном --z-modal из theme.css, а не числом', () => {
    expect(readSource(`${SRC}/styles/theme.css`)).toMatch(/--z-modal:\s*\d+/)
    expect(readSource(`${SRC}/components/BaseModal.vue`)).toContain('var(--z-modal)')
  })
})

describe.each(modalFiles)('%s', (file) => {
  const source = readSource(file)

  it('закрывается по Esc и клику на подложку через BaseModal: событие close, без собственного useOverlayDismiss и Teleport', () => {
    expect(source).toMatch(/<BaseModal\b[^>]*@close=/)
    expect(source).not.toContain('useOverlayDismiss(')
    expect(source).not.toContain('<Teleport')
  })

  it('диалог с role и доступным именем (aria-label или aria-labelledby на существующий заголовок)', () => {
    const tpl = template(file)
    const dialog = /<(?:div|form)\b[^>]*role="(?:alert)?dialog"[^>]*>/.exec(tpl)
    expect(dialog, 'нет role="dialog"').not.toBeNull()
    const tag = dialog![0]
    expect(tag).toContain('aria-modal="true"')
    expect(/aria-label=|aria-labelledby=/.test(tag), 'у диалога нет имени').toBe(true)

    const labelledBy = /:aria-labelledby="(\w+)"/.exec(tag)
    if (labelledBy) expect(tpl, 'нет заголовка с этим id').toContain(`:id="${labelledBy[1]}"`)
    const staticLabelledBy = /\saria-labelledby="([\w-]+)"/.exec(tag)
    if (staticLabelledBy) expect(tpl, 'нет заголовка с этим id').toContain(`id="${staticLabelledBy[1]}"`)
  })

  it('BaseModal — корень окна, без v-if (иначе Esc сработал бы у закрытого окна)', () => {
    const modal = /<BaseModal\b[^>]*>/.exec(template(file))
    expect(modal).not.toBeNull()
    expect(modal![0]).not.toContain('v-if')
  })

  it('слой не задаётся числом: z-index в стилях окна только локальный (меньше 10)', () => {
    const styles = source.slice(source.indexOf('<style') === -1 ? source.length : source.indexOf('<style'))
    const zIndexes = Array.from(styles.matchAll(/z-index:\s*(\d+)/g), (match) => Number(match[1]))
    expect(zIndexes.filter((value) => value >= 10)).toEqual([])
  })
})

describe('UI-04: подвал модальной формы закреплён', () => {
  const css = readStyles('src/styles/base.css')

  it('.modal-foot — sticky у нижнего края, с непрозрачным фоном карточки', () => {
    const foot = ruleBody(css, '.modal-foot')
    expect(declaration(foot, 'position')).toBe('sticky')
    expect(declaration(foot, 'bottom')).toBe('0')
    expect(declaration(foot, 'background')).toBe('var(--surface)')
  })

  it('отступ кнопок от края не раздувает нижний отступ карточки: padding-bottom компенсирован отрицательным margin', () => {
    const foot = ruleBody(css, '.modal-foot')
    expect(declaration(foot, 'padding-bottom')).toBe('12px')
    expect(declaration(foot, 'margin-bottom')).toBe('-12px')
  })

  it('нижний отступ оверлея с подвалом обнулён с повышенной специфичностью, иначе под подвалом просвечивает полоса', () => {
    expect(declaration(ruleBody(css, 'html .modal-overlay:has(.modal-foot)'), 'padding-bottom')).toBe('0')
  })
})
