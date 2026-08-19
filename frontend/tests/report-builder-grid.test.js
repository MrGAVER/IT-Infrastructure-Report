'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadAppWindow } = require('./load-app.js');

// Значения, созданные внутри jsdom vm-контекста, не проходят строгую deepStrictEqual по прототипу
// с обычными объектами Node.js даже при структурном совпадении — см. app.smoke.test.js.
const plain = (v) => JSON.parse(JSON.stringify(v));

const ENTITIES = [
  {
    key: 'information-systems', label: 'Информационные системы',
    fields: [{ name: 'name', label: 'Наименование', type: 'String', is_foreign_key: false },
             { name: 'status', label: 'Статус', type: 'String', is_foreign_key: false }],
    to_one: [], to_many: [{ name: 'devices', target: 'devices' }],
  },
  {
    key: 'devices', label: 'Устройства',
    fields: [{ name: 'name', label: 'Название', type: 'String', is_foreign_key: false }],
    to_one: [], to_many: [],
  },
];

function withEntities(win) {
  win.RB.entities = ENTITIES;
  win.RB.entitiesByKey = Object.fromEntries(ENTITIES.map((e) => [e.key, e]));
  return win;
}

test('rbColLetter(): буквенные обозначения колонок, включая переход через Z', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  assert.equal(win.rbColLetter(0), 'A');
  assert.equal(win.rbColLetter(25), 'Z');
  assert.equal(win.rbColLetter(26), 'AA');
  assert.equal(win.rbColLetter(27), 'AB');
  assert.equal(win.rbColLetter(52), 'BA');
});

test('rbCoverageForRows(): строка под вертикальным объединением помечена покрытой, соседние — нет', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  const rows = [
    { cells: [{ col: 0, rowspan: 2, colspan: 1 }] },
    { cells: [] },
    { cells: [] },
  ];
  assert.deepEqual([...win.rbCoverageForRows(rows, 0)], []);
  assert.deepEqual([...win.rbCoverageForRows(rows, 1)], [0]);
  assert.deepEqual([...win.rbCoverageForRows(rows, 2)], []);
});

test('rbCoverageForRows(): учитывает colspan объединённой ячейки-источника', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  const rows = [
    { cells: [{ col: 1, rowspan: 3, colspan: 2 }] },
    { cells: [] },
  ];
  assert.deepEqual([...win.rbCoverageForRows(rows, 1)].sort(), [1, 2]);
});

test('rbFlattenPaths(): поля сущности плюс поля через to_many-связь с маркером списка', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  const paths = win.rbFlattenPaths('information-systems');
  const byPath = Object.fromEntries(paths.map((p) => [p.path, p]));
  assert.ok(byPath['name'], 'должно быть прямое поле name');
  assert.equal(byPath['name'].hops, 0);
  assert.ok(byPath['devices[].name'], 'должно быть поле через связь-список');
  assert.equal(byPath['devices[].name'].many, true);
});

test('rbNewGridTemplate(): создаёт лист с 6 колонками, заголовочной и повторяющейся строкой', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  assert.equal(win.RB.editor.id, '');
  assert.equal(win.RB.editor.format, 'xlsx');
  assert.equal(sheet.columns.length, 6);
  assert.equal(sheet.rows.length, 2);
  assert.equal(sheet.rows[0].repeat, false);
  assert.equal(sheet.rows[1].repeat, true);
});

test('rbCollectGridConfig(): отбрасывает параметры без ключа, передаёт листы как есть', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  win.RB.editor.params = [{ key: 'org', label: 'Организация', default: '' }, { key: '', label: '', default: '' }];
  const cfg = win.rbCollectGridConfig();
  assert.equal(cfg.params.length, 1);
  assert.equal(cfg.params[0].key, 'org');
  assert.equal(cfg.sheets, win.RB.editor.sheets);
});

test('rbDropOnCell(): перетаскивание поля на нестроку-повторение включает повторение и привязывает данные', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewGridTemplate();
  win.RB.editor.activeSheet = 0;
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  win.RB.dragField = { path: 'name', entity: 'information-systems' };
  win.rbDropOnCell({ preventDefault() {} }, 0, 2);
  const row = sheet.rows[0];
  assert.equal(row.repeat, true);
  assert.equal(row.data_source.root_entity, 'information-systems');
  const cell = row.cells.find((c) => c.col === 2);
  assert.equal(cell.kind, 'field');
  assert.equal(cell.path, 'name');
});

test('rbDropOnCell(): поле из другой сущности в уже привязанную строку отклоняется', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(true)];
  sheet.rows[0].data_source.root_entity = 'devices';
  win.RB.dragField = { path: 'name', entity: 'information-systems' };
  win.rbDropOnCell({ preventDefault() {} }, 0, 0);
  assert.equal(sheet.rows[0].cells.length, 0, 'ячейка не должна быть создана при конфликте сущностей');
});

test('rbDropOnCell(): "№ по порядку" отклоняется вне повторяющейся строки', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  win.RB.dragField = { special: 'index' };
  win.rbDropOnCell({ preventDefault() {} }, 0, 0);
  assert.equal(sheet.rows[0].cells.length, 0);
});

test('rbDropOnCell(): "№ по порядку" создаёт ячейку kind=index в повторяющейся строке', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(true)];
  sheet.rows[0].data_source.root_entity = 'information-systems';
  win.RB.dragField = { special: 'index' };
  win.rbDropOnCell({ preventDefault() {} }, 0, 0);
  assert.equal(sheet.rows[0].cells[0].kind, 'index');
});

test('rbSetCellKind(): переключение на "formula" подставляет "=" по умолчанию', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  win.rbSetCellKind(0, 0, 'formula');
  assert.equal(sheet.rows[0].cells[0].text, '=');
});

test('rbSetCellStyle(): true записывает значение, false/"" удаляет ключ стиля', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  win.rbSetCellStyle(0, 0, 'bold', true);
  assert.equal(sheet.rows[0].cells[0].style.bold, true);
  win.rbSetCellStyle(0, 0, 'bold', false);
  assert.equal('bold' in sheet.rows[0].cells[0].style, false);
});

test('rbMergeSelection(): объединяет диапазон, удаляя вложенные ячейки (после подтверждения)', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.confirm = () => true;
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false), win.rbNewRow(false)];
  sheet.rows[0].cells = [{ col: 0, kind: 'static', text: 'A', style: {} }];
  sheet.rows[1].cells = [{ col: 1, kind: 'static', text: 'B', style: {} }];
  win.RB.selected = { sheet: 0, row: 0, col: 0 };
  win.RB.rangeEnd = { row: 1, col: 1 };
  win.rbMergeSelection();
  const anchor = sheet.rows[0].cells.find((c) => c.col === 0);
  assert.equal(anchor.colspan, 2);
  assert.equal(anchor.rowspan, 2);
  assert.equal(sheet.rows[1].cells.length, 0, 'вложенная ячейка B должна быть удалена');
});

test('rbMergeSelection(): объединение по вертикали через повторяющуюся строку запрещено', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false), win.rbNewRow(true)];
  win.RB.selected = { sheet: 0, row: 0, col: 0 };
  win.RB.rangeEnd = { row: 1, col: 0 };
  win.rbMergeSelection();
  assert.equal(sheet.rows[0].cells.length, 0, 'объединение не должно было произойти');
});

test('rbUnmergeCell(): сбрасывает colspan/rowspan объединённой ячейки к 1', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  sheet.rows[0].cells = [{ col: 0, colspan: 3, rowspan: 2, kind: 'static', text: 'X', style: {} }];
  win.rbUnmergeCell(0, 0);
  const cell = sheet.rows[0].cells[0];
  assert.equal(cell.colspan, 1);
  assert.equal(cell.rowspan, 1);
});

test('rbToggleRepeat(): нельзя включить повторение у строки, накрытой объединением сверху', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false), win.rbNewRow(false)];
  sheet.rows[0].cells = [{ col: 0, rowspan: 2, colspan: 1, kind: 'static', text: 'X', style: {} }];
  win.rbToggleRepeat(1);
  assert.equal(sheet.rows[1].repeat, false);
});

test('rbToggleRepeat(): включает/выключает повторение и очищает поля при выключении (после подтверждения)', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.confirm = () => true;
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  win.RB.paletteEntity = 'information-systems';
  win.rbToggleRepeat(0);
  assert.equal(sheet.rows[0].repeat, true);
  assert.equal(sheet.rows[0].data_source.root_entity, 'information-systems');
  sheet.rows[0].cells = [{ col: 0, kind: 'field', path: 'name', style: {} }];
  win.rbToggleRepeat(0);
  assert.equal(sheet.rows[0].repeat, false);
  assert.equal(sheet.rows[0].data_source, null);
  assert.equal(sheet.rows[0].cells[0].kind, 'static');
});

test('rbAddRowAt(): вставка внутри вертикального объединения растягивает rowspan, чтобы не разрывать его', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false), win.rbNewRow(false)];
  sheet.rows[0].cells = [{ col: 0, rowspan: 2, colspan: 1, kind: 'static', text: 'X', style: {} }];
  win.rbAddRowAt(0); // вставить между строкой 0 и прежней строкой 1 — внутри объединения
  assert.equal(sheet.rows.length, 3);
  assert.equal(sheet.rows[0].cells[0].rowspan, 3);
});

test('rbRemoveRow(): удаление строки внутри объединения уменьшает rowspan предыдущей ячейки', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewGridTemplate();
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false), win.rbNewRow(false), win.rbNewRow(false)];
  sheet.rows[0].cells = [{ col: 0, rowspan: 3, colspan: 1, kind: 'static', text: 'X', style: {} }];
  win.rbRemoveRow(1);
  assert.equal(sheet.rows.length, 2);
  assert.equal(sheet.rows[0].cells[0].rowspan, 2);
});

test('rbRemoveColumn(): сдвигает cell.col у последующих колонок и укорачивает объединения через удаляемую', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.confirm = () => true;
  win.rbNewGridTemplate();
  win.RB.editor.activeSheet = 0;
  const sheet = win.RB.editor.sheets[0];
  sheet.rows = [win.rbNewRow(false)];
  sheet.rows[0].cells = [
    { col: 0, colspan: 3, kind: 'static', text: 'A', style: {} },
    { col: 4, kind: 'static', text: 'B', style: {} },
  ];
  win.rbRemoveColumn(1); // колонка внутри объединения A (0..2)
  const cells = sheet.rows[0].cells;
  assert.equal(cells.find((c) => c.text === 'A').colspan, 2);
  assert.equal(cells.find((c) => c.text === 'B').col, 3);
});

test('rbEditGridTemplate(): подставляет сущность палитры из первой найденной повторяющейся строки', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  const cfg = { sheets: [{ title: 'Лист', columns: [{ width: 20 }], rows: [
    { height: 20, repeat: true, data_source: { root_entity: 'information-systems' }, cells: [] },
  ] }] };
  win.rbEditGridTemplate({ id: 't1', name: 'Т1', description: '', config: cfg });
  assert.equal(win.RB.paletteEntity, 'information-systems');
  assert.equal(win.RB.editor.id, 't1');
});

test('openReportBuilder()/rbRenderTemplatesList(): отображает список шаблонов обоих форматов', async () => {
  const templates = [
    { id: '1', name: 'Реестр ИС', format: 'xlsx', description: '', updated_at: null },
    { id: '2', name: 'Акт', format: 'docx', description: '', updated_at: null },
  ];
  const win = loadAppWindow({
    withReportBuilder: true,
    fetchImpl: (url) => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(
        String(url).includes('/report-builder/entities') ? ENTITIES :
        String(url).endsWith('/report-templates') ? templates : {}
      ),
      text: () => Promise.resolve('{}'),
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 20)); // дождаться начального showDashboard()
  await win.openReportBuilder();
  const html = win.document.getElementById('content').innerHTML;
  assert.match(html, /Реестр ИС/);
  assert.match(html, /Акт/);
  assert.match(html, /Excel \(\.xlsx\)/);
  assert.match(html, /Word \(\.docx\)/);
  // Действия — первая колонка таблицы (не последняя), чтобы не нужно было скролить к ним при
  // длинном описании/множестве колонок — см. отчёт пользователя.
  const headerRow = win.document.querySelector('table thead tr');
  const headerLabels = Array.from(headerRow.querySelectorAll('th')).map((th) => th.textContent.trim());
  assert.deepEqual(headerLabels, ['Действия', 'Название', 'Формат', 'Описание', 'Изменён']);
});

test('rbNewTemplate("docx"): открывает docx-редактор с одним стартовым блоком-заголовком', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewTemplate('docx');
  assert.equal(win.RB.editor.format, 'docx');
  assert.equal(win.RB.editor.blocks.length, 1);
  assert.equal(win.RB.editor.blocks[0].type, 'heading');
  const html = win.document.getElementById('content').innerHTML;
  assert.match(html, /Новый шаблон отчёта \(Word\)/);
});

test('rbEditTemplate(): docx-шаблон открывает docx-редактор с блоками из конфигурации', async () => {
  const win = loadAppWindow({
    withReportBuilder: true,
    fetchImpl: () => Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        id: '2', name: 'Акт', format: 'docx',
        config: { blocks: [{ type: 'heading', text: 'Приложение', level: 1 }, { type: 'table', root_entity: 'information-systems', columns: [{ header: 'Имя', source: 'field', path: 'name' }] }] },
      }),
      text: () => Promise.resolve('{}'),
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  await win.rbEditTemplate('2');
  assert.equal(win.RB.editor.format, 'docx');
  assert.equal(win.RB.editor.blocks.length, 2);
  assert.equal(win.RB.editor.blocks[1].type, 'table');
  const html = win.document.getElementById('content').innerHTML;
  assert.match(html, /Изменить шаблон отчёта \(Word\)/);
});

test('rbAddBlock()/rbRemoveBlock(): добавляют и удаляют блоки нужного типа', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.confirm = () => true;
  win.rbNewDocxTemplate();
  win.rbAddBlock('table');
  win.rbAddBlock('paragraph');
  win.rbAddBlock('page_break');
  assert.deepEqual(plain(win.RB.editor.blocks.map((b) => b.type)), ['heading', 'table', 'paragraph', 'page_break']);
  win.rbRemoveBlock(1);
  assert.deepEqual(plain(win.RB.editor.blocks.map((b) => b.type)), ['heading', 'paragraph', 'page_break']);
});

test('rbMoveBlock(): меняет местами соседние блоки, за границы массива не выходит', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewDocxTemplate();
  win.rbAddBlock('paragraph');
  const [first, second] = win.RB.editor.blocks;
  win.rbMoveBlock(0, 1);
  assert.equal(win.RB.editor.blocks[0], second);
  assert.equal(win.RB.editor.blocks[1], first);
  win.rbMoveBlock(0, -1); // уже наверху — не должно бросать и не должно ничего менять
  assert.equal(win.RB.editor.blocks[0], second);
});

test('rbAddTableColumn()/rbSetTableColumn(): добавляет колонку и меняет её поля', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewDocxTemplate();
  win.rbAddBlock('table');
  const bi = win.RB.editor.blocks.length - 1;
  win.rbAddTableColumn(bi);
  win.rbSetTableColumn(bi, 0, 'header', 'Наименование');
  win.rbSetTableColumn(bi, 0, 'path', 'name');
  const col = win.RB.editor.blocks[bi].columns[0];
  assert.equal(col.header, 'Наименование');
  assert.equal(col.path, 'name');
  assert.equal(col.source, 'field');
});

test('rbSetTableEntity(): при первой установке сущности ничего не спрашивает; при смене на другую — просит подтверждение и сбрасывает пути', () => {
  const win = withEntities(loadAppWindow({ withReportBuilder: true }));
  win.rbNewDocxTemplate();
  win.rbAddBlock('table');
  const bi = win.RB.editor.blocks.length - 1;
  win.rbSetTableEntity(bi, 'information-systems');
  assert.equal(win.RB.editor.blocks[bi].root_entity, 'information-systems');

  win.rbAddTableColumn(bi);
  win.rbSetTableColumn(bi, 0, 'path', 'name');
  win.confirm = () => true;
  win.rbSetTableEntity(bi, 'devices');
  assert.equal(win.RB.editor.blocks[bi].root_entity, 'devices');
  assert.equal(win.RB.editor.blocks[bi].columns[0].path, '', 'путь колонки должен сброситься при смене сущности');
});

test('rbCollectDocxConfig(): отбрасывает параметры без ключа, передаёт блоки как есть', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewDocxTemplate();
  win.RB.editor.params = [{ key: 'org', label: 'Организация', default: '' }, { key: '', label: '', default: '' }];
  const cfg = win.rbCollectDocxConfig();
  assert.equal(cfg.params.length, 1);
  assert.equal(cfg.params[0].key, 'org');
  assert.equal(cfg.blocks, win.RB.editor.blocks);
});

test('rbDocxPreviewHTML(): рендерит только табличные секции предпросмотра, с заголовками и строками', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  win.rbNewDocxTemplate();
  win.RB.preview = { sections: [{ title: 'Оборудование', headers: ['Имя', 'Серийный №'], rows: [['srv-01', 'SN-1']], total: 1 }] };
  win.rbRenderDocxEditor();
  const html = win.document.getElementById('content').innerHTML;
  assert.match(html, /Оборудование/);
  assert.match(html, /Серийный №/);
  assert.match(html, /srv-01/);
});
