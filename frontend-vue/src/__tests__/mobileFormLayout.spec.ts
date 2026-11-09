// F-05 (код-ревью main), продолжение: формы и редакторы на телефоне (390 px). Живая проверка показала, что форма устройства,
// редактор docx и форма правила порт-синхронизации раздвигались вбок шире окна, а прокручиваемые таблицы внутри них не давали
// подсказки. Причины две, и обе — в стилях, которых jsdom не считает, поэтому здесь проверяется исходник:
//  1. дорожка сетки «1fr» — это minmax(auto, 1fr): её минимум — ширина содержимого (10-колоночная таблица, select с длинным пунктом),
//     и сетка растягивается за окно. Нужен minmax(0, 1fr);
//  2. таблица или select во flex-строке не сжимается ниже собственной ширины (min-width: auto) — нужен min-width: 0 и потолок.
// Поведение (рамка прокрутки у таблиц) покрыто тестами самих компонентов; вид в браузере — замером scrollWidth в e2e/ручной приёмке.
import { describe, expect, it } from 'vitest'
import { mediaBlock, readStyles, ruleBody } from './cssSource'

/** Файлы, у которых при проверке в браузере форма выходила за окно. */
const FORMS = ['src/components/DeviceFormModal.vue', 'src/components/DocxTableBlockEditor.vue', 'src/components/PortSyncRuleFormModal.vue']

/** Все значения grid-template-columns файла. */
function gridTemplates(file: string): string[] {
  return Array.from(readStyles(file).matchAll(/grid-template-columns:\s*([^;]+);/g), (match) => match[1].trim())
}

describe('формы на телефоне: сетки не растягиваются шире окна', () => {
  it.each(FORMS)('%s: каждая гибкая дорожка — minmax(0, Nfr), а не голое «Nfr»', (file) => {
    const templates = gridTemplates(file)
    expect(templates.length).toBeGreaterThan(0)
    for (const template of templates) {
      const withoutSafeTracks = template.replace(/minmax\(0,\s*[\d.]+fr\)/g, '')
      expect(withoutSafeTracks, `${file}: «${template}»`).not.toMatch(/\bfr\b|\dfr/)
    }
  })

  it('форма устройства: на телефоне одна колонка minmax(0, 1fr) — таблица интерфейсов листается внутри обёртки', () => {
    const mobile = mediaBlock(readStyles('src/components/DeviceFormModal.vue'), '(max-width: 640px)')
    expect(mobile).not.toBeNull()
    expect(ruleBody(mobile!, '.form-grid')).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  })

  it('редактор docx: поля строк колонок и фильтров сжимаются (min-width: 0), на телефоне колонка раскладывается в два яруса', () => {
    const css = readStyles('src/components/DocxTableBlockEditor.vue')
    for (const selector of ['.column-row input,\n.column-row select', '.filter-row input,\n.filter-row select', '.path-row input', '.path-row select']) {
      const body = css.slice(css.indexOf(selector))
      expect(body.slice(0, body.indexOf('}')), selector).toMatch(/min-width:\s*0/)
    }
    // Select «Вставить поле…» берёт ширину самого длинного пути (до 750 px) — без потолка он вытесняет поле ввода за окно.
    expect(ruleBody(css, '.path-row select')).toMatch(/max-width:\s*\d+%/)

    const mobile = mediaBlock(css, '(max-width: 640px)')
    expect(mobile).not.toBeNull()
    expect(ruleBody(mobile!, '.column-row')).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(0,\s*1fr\)/)
    expect(ruleBody(mobile!, '.column-actions')).toMatch(/grid-column:\s*1\s*\/\s*-1/)
  })
})

describe('таблицы внутри форм: прокрутка — только через ScrollableTableWrap', () => {
  it.each([
    'src/components/DeviceInterfacesEditor.vue',
    'src/components/InterfaceSubinterfacesEditor.vue',
    'src/components/GridPreviewTable.vue',
    'src/views/ReportDocxEditorView.vue',
  ])('%s: нет собственного overflow-x — он в обёртке, а с ним и подсказка о прокрутке', (file) => {
    expect(readStyles(file)).not.toMatch(/overflow-x\s*:/)
  })
})
