// UI-04 (ревью 2.158.0): структурная проверка ВСЕХ модальных окон приложения. Новая модалка, забывшая подключить закрытие по Esc или
// назвать диалог, не пройдёт этот тест — без него правки по 33 файлам вернулись бы по одному при первом же копировании формы.
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { declaration, readSource, readStyles, ruleBody } from '../../__tests__/cssSource'

const COMPONENTS_DIR = 'src/components'
const modalFiles = readdirSync(path.resolve(process.cwd(), COMPONENTS_DIR))
  .filter((name) => name.endsWith('.vue'))
  .filter((name) => readSource(`${COMPONENTS_DIR}/${name}`).includes('class="overlay'))

function template(file: string): string {
  const source = readSource(`${COMPONENTS_DIR}/${file}`)
  const end = source.indexOf('<style')
  return source.slice(source.indexOf('<template>'), end === -1 ? undefined : end)
}

describe('UI-04: модальные окна', () => {
  it('найдены все модалки (33 файла) — иначе проверки ниже ничего не охватывают', () => {
    expect(modalFiles.length).toBeGreaterThanOrEqual(33)
  })

  it.each(modalFiles)('%s: закрывается по Esc — вызывает useOverlayDismiss', (file) => {
    expect(readSource(`${COMPONENTS_DIR}/${file}`)).toContain('useOverlayDismiss(')
  })

  it.each(modalFiles)('%s: диалог с role и доступным именем (aria-label или aria-labelledby на существующий заголовок)', (file) => {
    const tpl = template(file)
    const dialog = /<div\b[^>]*role="(?:alert)?dialog"[^>]*>/.exec(tpl)
    expect(dialog, 'нет role="dialog"').not.toBeNull()
    const tag = dialog![0]
    expect(tag).toContain('aria-modal="true"')
    expect(/aria-label=|aria-labelledby=/.test(tag), 'у диалога нет имени').toBe(true)

    const labelledBy = /:aria-labelledby="(\w+)"/.exec(tag)
    if (labelledBy) expect(tpl, 'нет заголовка с этим id').toContain(`:id="${labelledBy[1]}"`)
    const staticLabelledBy = /\saria-labelledby="([\w-]+)"/.exec(tag)
    if (staticLabelledBy) expect(tpl, 'нет заголовка с этим id').toContain(`id="${staticLabelledBy[1]}"`)
  })

  it.each(modalFiles)('%s: подложка — корень окна, без v-if (иначе Esc сработал бы у закрытого окна)', (file) => {
    const overlay = /<div class="overlay[^>]*>/.exec(template(file))
    expect(overlay).not.toBeNull()
    expect(overlay![0]).not.toContain('v-if')
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
    expect(declaration(ruleBody(css, 'html .overlay:has(.modal-foot)'), 'padding-bottom')).toBe('0')
  })
})
