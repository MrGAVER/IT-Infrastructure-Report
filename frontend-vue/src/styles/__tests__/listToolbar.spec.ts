import { describe, expect, it } from 'vitest'
import { declaration, mediaBlock, readSource, readStyles, ruleBody } from '../../__tests__/cssSource'

// UI-10 и UI-11 (ревью merge/review-2158-executors, поток Исполнителя 2): обрезанные плейсхолдеры поиска и «неровные» панели
// фильтров. jsdom раскладку не считает (css: false), поэтому проверяются исходники; итоговую геометрию в настоящем браузере
// проверяет e2e/filled-data.spec.ts.

const toolbarCss = readStyles('src/styles/list-toolbar.css')
const VIEWS = ['Devices', 'Connections', 'InformationSystems', 'VLANs'] as const

/** Фрагмент шаблона от <div class="filter-bar …"> до карточки таблицы / следующего блока экрана. */
function toolbarMarkup(view: string): string {
  const source = readSource(`src/views/${view}View.vue`)
  const start = source.indexOf('<div class="filter-bar list-toolbar">')
  expect(start, `${view}View: нет <div class="filter-bar list-toolbar">`).toBeGreaterThan(-1)
  const end = source.search(/\n {4}<(div class="table-card|VLANDomainsPanel)/)
  return source.slice(start, end)
}

describe('styles/list-toolbar.css', () => {
  it('поиск не уже 240px и растёт от 300px: плейсхолдер перестаёт обрезаться (UI-10)', () => {
    const body = ruleBody(toolbarCss, '.list-toolbar .search-box')
    expect(declaration(body, 'flex')).toBe('1 1 300px')
    expect(declaration(body, 'min-width')).toBe('min(100%, 240px)')
    expect(declaration(body, 'max-width')).toBe('460px')
  })

  it('селект фильтра имеет фиксированную ширину 200px, а не ширину самой длинной опции (UI-11)', () => {
    const body = ruleBody(toolbarCss, '.list-toolbar select.fbtn')
    expect(declaration(body, 'width')).toBe('200px')
    expect(declaration(body, 'flex')).toBe('0 1 200px')
    expect(declaration(body, 'text-overflow')).toBe('ellipsis')
    // не шире строки: на телефоне селект не должен вылезать за экран
    expect(declaration(ruleBody(toolbarCss, '.list-toolbar .fbtn'), 'max-width')).toBe('100%')
  })

  it('фильтры переносятся внутри своей группы, а кнопки — одним блоком справа (UI-11)', () => {
    expect(declaration(ruleBody(toolbarCss, '.list-toolbar .filter-fields'), 'flex')).toBe('1 1 480px')
    const actions = ruleBody(toolbarCss, '.list-toolbar .filter-actions')
    expect(declaration(actions, 'flex')).toBe('0 0 auto')
    expect(declaration(actions, 'margin-left')).toBe('auto')
    expect(declaration(actions, 'flex-wrap')).toBe('wrap')
  })

  it('на телефоне (≤760px) поиск и кнопки действий занимают всю строку', () => {
    const phone = mediaBlock(toolbarCss, '(max-width: 760px)')
    expect(phone).not.toBeNull()
    expect(declaration(ruleBody(phone!, '.list-toolbar .search-box'), 'flex')).toBe('1 1 100%')
    expect(declaration(ruleBody(phone!, '.list-toolbar .filter-actions'), 'flex')).toBe('1 1 100%')
    expect(declaration(ruleBody(phone!, '.list-toolbar .filter-actions'), 'margin-left')).toBe('0')
  })

  it('все правила под .list-toolbar — другие экраны со своими .search-box и .chip-group не затрагиваются', () => {
    const css = toolbarCss.replace(/\/\*[\s\S]*?\*\//g, '')
    const selectors = [...css.matchAll(/(^|[{}])\s*([^{}@]+)\{/g)].map((m) => m[2].trim()).filter(Boolean)
    expect(selectors.length).toBeGreaterThan(5)
    for (const selector of selectors) {
      for (const part of selector.split(',')) expect(part.trim(), `селектор «${part.trim()}»`).toMatch(/^\.list-toolbar\b/)
    }
  })
})

describe.each(VIEWS)('%sView.vue — панель фильтров', (view) => {
  const source = readSource(`src/views/${view}View.vue`)
  const markup = toolbarMarkup(view)

  it('подключает общий файл и делит панель на .filter-fields и .filter-actions', () => {
    expect(source).toContain("import '../styles/list-toolbar.css'")
    expect(markup).toContain('<div class="filter-fields">')
    expect(markup).toContain('<div class="filter-actions">')
    expect(markup.indexOf('filter-fields')).toBeLessThan(markup.indexOf('filter-actions'))
  })

  it('кнопки действий («Обновить» и т. п.) только в .filter-actions, поле поиска — только в .filter-fields', () => {
    const [fields, actions] = markup.split('<div class="filter-actions">')
    expect(fields).toContain('class="search-box"')
    expect(fields).not.toContain('Обновить')
    expect(actions).toContain('Обновить')
    expect(actions).not.toContain('search-box')
  })

  it('не держит собственных копий .search-box / .chip-group / .spacer — они в общем файле', () => {
    const styles = readStyles(`src/views/${view}View.vue`)
    for (const selector of ['.filter-bar', '.search-box', '.chip-group', '.spacer', '.fbtn']) {
      expect(ruleBody(styles, selector), `${view}View: правило ${selector}`).toBeNull()
    }
    expect(source).not.toContain('class="spacer"')
  })

  it('плейсхолдер поиска короткий (до 40 символов), полная подсказка — в title и aria-label (UI-10)', () => {
    const input = /<input[^>]*type="text"[\s\S]*?\/>/.exec(markup.split('class="search-box"')[1])![0]
    const placeholder = /placeholder="([^"]+)"/.exec(input)![1]
    const title = /title="([^"]+)"/.exec(input)![1]
    const ariaLabel = /aria-label="([^"]+)"/.exec(input)![1]
    expect(placeholder.length).toBeLessThanOrEqual(40)
    expect(title).toBe(ariaLabel)
    expect(title.length).toBeGreaterThanOrEqual(placeholder.length - 1) // полная подсказка не короче сокращённой (без «…»)
  })
})

describe('ConnectionsView.vue — «Визуальный режим» (UI-11)', () => {
  it('кнопка лежит в группе действий справа, а не отдельным элементом панели', () => {
    const [fields, actions] = toolbarMarkup('Connections').split('<div class="filter-actions">')
    expect(actions).toContain('Визуальный режим')
    expect(fields).not.toContain('Визуальный режим')
  })

  it('главное действие «Добавить подключение» остаётся последним (крайним справа)', () => {
    const actions = toolbarMarkup('Connections').split('<div class="filter-actions">')[1]
    expect(actions.lastIndexOf('Добавить подключение')).toBeGreaterThan(actions.indexOf('Визуальный режим'))
  })
})

describe('DevicesView.vue — селекты фильтров', () => {
  it('у селектов «Здание» и «Тип устройства» есть доступное имя (в них первая опция — «…: все»)', () => {
    const markup = toolbarMarkup('Devices')
    expect(markup).toContain('aria-label="Здание"')
    expect(markup).toContain('aria-label="Тип устройства"')
  })
})
