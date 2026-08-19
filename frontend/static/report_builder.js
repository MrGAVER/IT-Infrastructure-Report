/*
 * Конструктор произвольных отчётов — визуальный grid-редактор листа Excel (формат xlsx).
 * Подключается после app.js. Переиспользует общие хелперы core.js: api, get(), esc(), notify(),
 * notifyError(), withBusyButton(), showDashboard() и общие CSS-классы (.btn/.panel/.modal/.dialog/
 * .formgrid/.field/.nested-row) — новые классы см. app.css (секция "rbg-*").
 *
 * Формат конфигурации листа (config.sheets[i]) описан подробно в
 * backend/app/services/report_grid.py — этот файл строит и редактирует ровно такую структуру
 * (лист = набор колонок с шириной + набор строк-ячеек с позицией/объединением/стилем) и
 * отправляет её как есть в POST/PUT /api/v1/report-templates: для API config — непрозрачный JSON,
 * вся структурная валидация выполняется на сервере при сохранении/предпросмотре.
 *
 * Редактирование Word-шаблонов (.docx) в этом визуальном редакторе не реализовано — формат xlsx
 * это единственное, что здесь можно создавать/менять; существующие docx-шаблоны по-прежнему можно
 * формировать, дублировать, смотреть историю версий и удалять из списка шаблонов.
 */
var RB = {
  entities: [], entitiesByKey: {}, templates: [], editor: null, preview: null,
  selected: null,   // {sheet, row, col} — col===null означает "выбрана строка целиком" (настройки строки)
  rangeEnd: null,   // {row, col} — конец диапазона при Shift+клике, для объединения ячеек
  paletteEntity: '',
  dragField: null,  // {path,label,entity} для поля БД или {special:'index'|'formula'} — между dragstart и drop
};

const RB_FILTER_OPS = [
  ['eq', 'равно'], ['ne', 'не равно'], ['contains', 'содержит'], ['not_contains', 'не содержит'],
  ['not_empty', 'не пусто'], ['is_true', 'да/включено'], ['is_false', 'нет/выключено'],
];
const RB_NUMBER_FORMATS = [
  ['', 'Общий'], ['0', 'Целое число'], ['0.00', 'Дробное (2 знака)'], ['0%', 'Процент'],
  ['# ##0.00', 'С разделителем разрядов'], ['DD.MM.YYYY', 'Дата'], ['DD.MM.YYYY HH:MM', 'Дата и время'],
];

// ---------- Метаданные сущностей (палитра полей + панель источника данных строки) ----------

async function rbLoadEntities() {
  if (RB.entities.length) return;
  RB.entities = await get(api + '/report-builder/entities');
  RB.entitiesByKey = Object.fromEntries(RB.entities.map(e => [e.key, e]));
}

function rbLabel(entityKey) { return RB.entitiesByKey[entityKey]?.label || entityKey; }

// Плоский список путей полей до 2 связей вглубь (field / relation.field / relation[].relation2.field)
// для палитры и для выпадающего списка-помощника рядом с текстовым полем пути. Ровно один сегмент
// "[]" на путь — то же ограничение, что и в report_engine.py на бэкенде.
function rbFlattenPaths(entityKey, maxHops = 2) {
  const out = [];
  const seen = new Set();
  function walk(curKey, segs, labels, hops, manyUsed) {
    const info = RB.entitiesByKey[curKey];
    if (!info) return;
    for (const f of info.fields) {
      const path = [...segs, f.name].join('.');
      if (seen.has(path)) continue;
      seen.add(path);
      out.push({ path, label: [...labels, f.label].join(' → '), hops, many: manyUsed });
    }
    if (hops >= maxHops) return;
    for (const rel of info.to_one) walk(rel.target, [...segs, rel.name], [...labels, rbLabel(rel.target)], hops + 1, manyUsed);
    if (!manyUsed) for (const rel of info.to_many) walk(rel.target, [...segs, rel.name + '[]'], [...labels, rbLabel(rel.target) + ' (список)'], hops + 1, true);
  }
  walk(entityKey, [], [], 0, false);
  return out.slice(0, 500);
}

function rbFieldPickerHTML(entityKey, targetInputId) {
  if (!entityKey) return '';
  const options = rbFlattenPaths(entityKey);
  const groups = { 0: [], 1: [], 2: [] };
  for (const o of options) (groups[o.hops] || groups[2]).push(o);
  const optgroup = (title, items) => items.length
    ? `<optgroup label="${esc(title)}">${items.map(o => `<option value="${esc(o.path)}">${esc(o.label)}</option>`).join('')}</optgroup>` : '';
  return `<select class="rbg-field-picker" onchange="if(this.value){document.getElementById('${targetInputId}').value=this.value;document.getElementById('${targetInputId}').dispatchEvent(new Event('change'));this.selectedIndex=0;}">
    <option value="">Вставить поле…</option>
    ${optgroup('Поле сущности', groups[0])}
    ${optgroup('Через одну связь', groups[1])}
    ${optgroup('Через две связи (в т.ч. списки)', groups[2])}
  </select>`;
}

function rbEntityOptionsHTML(selected) {
  return `<option value="">— выберите сущность —</option>` +
    RB.entities.map(e => `<option value="${esc(e.key)}" ${e.key === selected ? 'selected' : ''}>${esc(e.label)}</option>`).join('');
}

function rbExpandOptionsHTML(entityKey, selected) {
  const info = RB.entitiesByKey[entityKey];
  const rels = info ? info.to_many : [];
  return `<option value="">— без циклического вывода (1 строка на запись) —</option>` +
    rels.map(r => `<option value="${esc(r.name)}" ${r.name === selected ? 'selected' : ''}>${esc(r.name)} → ${esc(rbLabel(r.target))}</option>`).join('');
}

function rbColLetter(i) {
  let s = '', n = i + 1;
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

// ---------- Список шаблонов ----------

async function openReportBuilder() {
  resource = null;
  await rbLoadEntities();
  RB.templates = await get(api + '/report-templates');
  RB.editor = null;
  rbRenderTemplatesList();
}

function rbRenderTemplatesList() {
  const content = document.getElementById('content');
  content.innerHTML = `<div class="top"><div><h2>🧩 Конструктор отчётов</h2><div class="muted">Произвольные отчёты на основе данных реестра — визуальный редактор листа Excel: перетаскивание полей на лист, объединение ячеек, стили, формулы</div></div><div class="actions"><button class="btn" onclick="rbNewTemplate('xlsx')">+ Новый Excel-шаблон</button> <button class="btn gray" onclick="rbNewTemplate('docx')">+ Новый Word-шаблон</button> <button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div>
  <div class="panel"><div class="tablewrap"><table><thead><tr><th>Действия</th><th>Название</th><th>Формат</th><th>Описание</th><th>Изменён</th></tr></thead><tbody>
  ${RB.templates.length ? RB.templates.map(t => `<tr>
    <td>
      <button class="btn gray" onclick="rbEditTemplate('${t.id}')">Изменить</button>
      <button class="btn" onclick="rbGenerateTemplate('${t.id}')">Сформировать</button>
      <button class="btn gray" onclick="rbDuplicateTemplate('${t.id}')">Дублировать</button>
      <button class="btn gray" onclick="rbShowVersionHistory('${t.id}')">История</button>
      <button class="btn red" onclick="rbDeleteTemplate('${t.id}')">Удалить</button>
    </td>
    <td><b>${esc(t.name)}</b></td>
    <td>${t.format === 'docx' ? 'Word (.docx)' : 'Excel (.xlsx)'}</td>
    <td class="muted" style="white-space:normal;max-width:420px" title="${esc(t.description || '')}">${esc(t.description || '')}</td>
    <td class="muted">${t.updated_at ? new Date(t.updated_at).toLocaleString('ru-RU') : ''}</td>
  </tr>`).join('') : `<tr><td colspan="5" class="muted">Пока нет ни одного шаблона отчёта — создайте первый кнопкой выше.</td></tr>`}
  </tbody></table></div></div>`;
}

// ---------- История версий ----------

async function rbShowVersionHistory(id) {
  let t, versions;
  try {
    t = RB.templates.find(x => x.id === id) || await get(api + `/report-templates/${id}`);
    versions = await get(api + `/report-templates/${id}/versions`);
  } catch (e) { notifyError(e); return; }
  const content = document.getElementById('content');
  content.innerHTML = `<div class="top"><div><h2>История версий: ${esc(t.name)}</h2><div class="muted">${versions.length ? `${versions.length} сохранённых версий` : 'Шаблон ещё не изменялся после создания'}</div></div><div class="actions"><button class="btn gray" onclick="openReportBuilder()">← К списку шаблонов</button></div></div>
  <div class="panel"><div class="tablewrap"><table><thead><tr><th>Версия</th><th>Название на тот момент</th><th>Формат</th><th>Сохранена</th><th>Действия</th></tr></thead><tbody>
  ${versions.length ? versions.map(v => `<tr>
    <td>№${v.version_number}</td>
    <td>${esc(v.name)}</td>
    <td>${v.format === 'docx' ? 'Word (.docx)' : 'Excel (.xlsx)'}</td>
    <td class="muted">${v.created_at ? new Date(v.created_at).toLocaleString('ru-RU') : ''}</td>
    <td><button class="btn gray" onclick="rbRestoreVersion('${id}','${v.id}',this)">Восстановить</button></td>
  </tr>`).join('') : `<tr><td colspan="5" class="muted">История появится после первого изменения этого шаблона.</td></tr>`}
  </tbody></table></div></div>`;
}

async function rbRestoreVersion(templateId, versionId, btn) {
  if (!confirm('Восстановить эту версию? Текущее состояние шаблона тоже будет сохранено в историю — откат обратим.')) return;
  await withBusyButton(btn, async () => {
    try {
      await get(api + `/report-templates/${templateId}/versions/${versionId}/restore`, { method: 'POST' });
      notify('Версия восстановлена', 'success');
      RB.templates = await get(api + '/report-templates');
      await rbShowVersionHistory(templateId);
    } catch (e) { notifyError(e); }
  });
}

async function rbDeleteTemplate(id) {
  if (!confirm('Удалить этот шаблон отчёта? Действие необратимо.')) return;
  try { await get(api + `/report-templates/${id}`, { method: 'DELETE' }); await openReportBuilder(); }
  catch (e) { notifyError(e); }
}

async function rbDuplicateTemplate(id) {
  try { await get(api + `/report-templates/${id}/duplicate`, { method: 'POST' }); await openReportBuilder(); }
  catch (e) { notifyError(e); }
}

async function rbGenerateTemplate(id) {
  const t = RB.templates.find(x => x.id === id) || await get(api + `/report-templates/${id}`);
  const cfg = t.config || {};
  const paramDefs = cfg.params || [];
  const params = {};
  for (const p of paramDefs) {
    const v = prompt(p.label || p.key, p.default || '');
    if (v === null) return; // отменено пользователем
    params[p.key] = v;
  }
  try {
    const r = await get(api + `/report-templates/${id}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }) });
    window.location = r.download_url;
  } catch (e) { notifyError(e); }
}

// ---------- Новый / открыть шаблон ----------

function rbNewTemplate(format) {
  if (format === 'docx') {
    notify('Word-шаблоны: визуальный редактор для .docx пока не реализован — в этой версии конструктора доступен только Excel. Формирование, дублирование и история уже существующих Word-шаблонов работают как раньше.', 'info');
    return;
  }
  rbNewGridTemplate();
}

async function rbEditTemplate(id) {
  const t = await get(api + `/report-templates/${id}`);
  if (t.format !== 'xlsx') {
    notify('Word-шаблоны: визуальный редактор для .docx пока не реализован. Формирование, дублирование, история и удаление доступны из списка шаблонов.', 'info');
    return;
  }
  rbEditGridTemplate(t);
}

// ---------- Модель grid-редактора ----------

function rbNewRow(repeat = false) {
  return { height: 20, repeat, data_source: repeat ? { root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '' } : null, cells: [] };
}

function rbNewGridSheet(n = 1) {
  const cols = 6;
  return {
    title: `Лист ${n}`,
    columns: Array.from({ length: cols }, () => ({ width: 20 })),
    rows: [
      { height: 24, repeat: false, data_source: null, cells: [{ col: 0, colspan: cols, kind: 'static', text: 'Новый лист', style: { bold: true, align: 'center', bg: '#EEF2FF' } }] },
      rbNewRow(true),
    ],
  };
}

function rbNewGridTemplate() {
  RB.editor = { id: '', name: '', description: '', format: 'xlsx', params: [], sheets: [rbNewGridSheet(1)], activeSheet: 0 };
  RB.preview = null; RB.selected = null; RB.rangeEnd = null; RB.paletteEntity = '';
  rbRenderGridEditor();
}

function rbEditGridTemplate(t) {
  const cfg = t.config || {};
  const sheets = (cfg.sheets && cfg.sheets.length) ? cfg.sheets : [rbNewGridSheet(1)];
  RB.editor = { id: t.id, name: t.name, description: t.description || '', format: 'xlsx', params: cfg.params || [], sheets, activeSheet: 0 };
  RB.preview = null; RB.selected = null; RB.rangeEnd = null;
  RB.paletteEntity = sheets[0].rows.find(r => r.repeat && r.data_source && r.data_source.root_entity)?.data_source.root_entity || '';
  rbRenderGridEditor();
}

function rbCurSheet() { return RB.editor.sheets[RB.editor.activeSheet]; }

function rbCollectGridConfig() {
  return { params: RB.editor.params.filter(p => p.key), sheets: RB.editor.sheets };
}

// ---------- Листы ----------

function rbSwitchSheet(si) { RB.editor.activeSheet = si; RB.selected = null; RB.rangeEnd = null; rbRenderGridEditor(); }

function rbAddSheet() {
  RB.editor.sheets.push(rbNewGridSheet(RB.editor.sheets.length + 1));
  RB.editor.activeSheet = RB.editor.sheets.length - 1;
  RB.selected = null; RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbRemoveSheet(si) {
  if (RB.editor.sheets.length <= 1) { notify('В шаблоне должен остаться хотя бы один лист.', 'error'); return; }
  if (!confirm('Удалить лист целиком со всеми ячейками?')) return;
  RB.editor.sheets.splice(si, 1);
  if (RB.editor.activeSheet >= RB.editor.sheets.length) RB.editor.activeSheet = RB.editor.sheets.length - 1;
  RB.selected = null; RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbSetSheetTitle(si, v) { RB.editor.sheets[si].title = v; rbRenderGridEditor(); }

// ---------- Колонки ----------

function rbAddColumn() { rbCurSheet().columns.push({ width: 20 }); rbRenderGridEditor(); }

function rbRemoveColumn(ci) {
  const sheet = rbCurSheet();
  if (sheet.columns.length <= 1) { notify('На листе должна остаться хотя бы одна колонка.', 'error'); return; }
  const hasContent = sheet.rows.some(r => r.cells.some(c => c.col === ci || (c.col < ci && c.col + (c.colspan || 1) > ci)));
  if (hasContent && !confirm('В этой колонке (или в объединении через неё) есть содержимое — удалить вместе с колонкой?')) return;
  for (const row of sheet.rows) {
    row.cells = row.cells.filter(c => c.col !== ci).map(c => c.col > ci ? { ...c, col: c.col - 1 } : c);
    for (const c of row.cells) {
      const span = c.colspan || 1;
      if (c.col < ci && c.col + span > ci) c.colspan = Math.max(1, span - 1);
    }
  }
  sheet.columns.splice(ci, 1);
  RB.selected = null; RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbSetColWidth(ci, v) { rbCurSheet().columns[ci].width = Math.max(4, Number(v) || 20); rbRenderGridEditor(); }

// ---------- Строки ----------

function rbAddRowAt(ri) {
  const sheet = rbCurSheet();
  const insertAt = ri + 1;
  // Объединения по вертикали, "перешагивающие" точку вставки, растягиваем на 1 — иначе новая
  // строка окажется внутри визуально разорванного объединения.
  for (let r = 0; r < insertAt; r++) {
    for (const c of sheet.rows[r].cells) {
      const span = c.rowspan || 1;
      if (r + span > insertAt) c.rowspan = span + 1;
    }
  }
  sheet.rows.splice(insertAt, 0, rbNewRow(false));
  rbRenderGridEditor();
}

function rbRemoveRow(ri) {
  const sheet = rbCurSheet();
  if (sheet.rows.length <= 1) { notify('На листе должна остаться хотя бы одна строка.', 'error'); return; }
  if (sheet.rows[ri].cells.length && !confirm('В строке есть содержимое — удалить вместе со строкой?')) return;
  for (let r = 0; r < ri; r++) {
    for (const c of sheet.rows[r].cells) {
      const span = c.rowspan || 1;
      if (r + span > ri) c.rowspan = Math.max(1, span - 1);
    }
  }
  sheet.rows.splice(ri, 1);
  RB.selected = null; RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbSetRowHeight(ri, v) { rbCurSheet().rows[ri].height = Math.max(10, Number(v) || 20); rbRenderGridEditor(); }

function rbRowSpanCoverage(sheet, rowIndex) { return rbCoverageForRows(sheet.rows, rowIndex); }

// Общая для редактора и предпросмотра: какие колонки в строке rowIndex заняты вертикальным
// объединением, начавшимся в одной из строк ВЫШЕ (col -> "не рисовать здесь отдельную ячейку,
// её и так покрывает rowSpan ячейки сверху" — как в обычной HTML-таблице).
function rbCoverageForRows(rows, rowIndex) {
  const covered = new Set();
  for (let r = 0; r < rowIndex; r++) {
    for (const cell of rows[r].cells) {
      const rowspan = cell.rowspan || 1;
      if (r + rowspan > rowIndex) {
        const colspan = cell.colspan || 1;
        for (let c = cell.col; c < cell.col + colspan; c++) covered.add(c);
      }
    }
  }
  return covered;
}

function rbToggleRepeat(ri) {
  const sheet = rbCurSheet();
  const row = sheet.rows[ri];
  if (!row.repeat) {
    if (rbRowSpanCoverage(sheet, ri).size) { notify('Эта строка частично охвачена вертикальным объединением сверху — сначала разъедините ячейки.', 'error'); return; }
    if (row.cells.some(c => (c.rowspan || 1) > 1)) { notify('В строке есть вертикальное объединение — сначала разъедините ячейки, затем включите повторение.', 'error'); return; }
    row.repeat = true;
    row.data_source = { root_entity: RB.paletteEntity || '', expand: '', include_empty_expand: true, filters: [], sort_by: '' };
  } else {
    const hadBound = row.cells.some(c => c.kind === 'field' || c.kind === 'index');
    if (hadBound && !confirm('В строке есть ячейки, привязанные к данным (поле/№) — при отключении повторения они станут пустым текстом. Продолжить?')) return;
    for (const c of row.cells) if (c.kind === 'field' || c.kind === 'index') { c.kind = 'static'; c.text = ''; delete c.path; }
    row.repeat = false; row.data_source = null;
  }
  RB.selected = { sheet: RB.editor.activeSheet, row: ri, col: null };
  rbRenderGridEditor();
}

function rbSetRowEntity(ri, entityKey) {
  const row = rbCurSheet().rows[ri];
  const hadFields = row.cells.some(c => c.kind === 'field');
  if (hadFields && row.data_source.root_entity && row.data_source.root_entity !== entityKey) {
    if (!confirm('Смена сущности сбросит привязку полей в этой строке (пути относятся к прежней сущности). Продолжить?')) return;
    for (const c of row.cells) if (c.kind === 'field') { c.kind = 'static'; c.text = ''; delete c.path; }
  }
  row.data_source.root_entity = entityKey;
  row.data_source.expand = '';
  RB.paletteEntity = entityKey;
  rbRenderGridEditor();
}
function rbSetRowExpand(ri, v) { rbCurSheet().rows[ri].data_source.expand = v; rbRenderGridEditor(); }
function rbSetRowSort(ri, v) { rbCurSheet().rows[ri].data_source.sort_by = v; rbRenderGridEditor(); }
function rbSetRowIncludeEmpty(ri, v) { rbCurSheet().rows[ri].data_source.include_empty_expand = v; }
function rbAddRowFilter(ri) { rbCurSheet().rows[ri].data_source.filters.push({ path: '', op: 'eq', value: '' }); rbRenderGridEditor(); }
function rbRemoveRowFilter(ri, fi) { rbCurSheet().rows[ri].data_source.filters.splice(fi, 1); rbRenderGridEditor(); }
function rbSetRowFilter(ri, fi, key, v) { rbCurSheet().rows[ri].data_source.filters[fi][key] = v; rbRenderGridEditor(); }

// ---------- Выбор ячеек / диапазона ----------

function rbCellAt(row, col) { return row.cells.find(c => c.col === col); }

function rbSelectCell(si, ri, ci, ev) {
  RB.editor.activeSheet = si;
  if (ev && ev.shiftKey && RB.selected && RB.selected.sheet === si && RB.selected.col !== null) {
    RB.rangeEnd = { row: ri, col: ci };
  } else {
    RB.selected = { sheet: si, row: ri, col: ci };
    RB.rangeEnd = null;
  }
  rbRenderGridEditor();
}

function rbSelectRow(si, ri) {
  RB.editor.activeSheet = si;
  RB.selected = { sheet: si, row: ri, col: null };
  RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbSelectionRect() {
  if (!RB.selected || RB.selected.col === null || !RB.rangeEnd) return null;
  const r1 = Math.min(RB.selected.row, RB.rangeEnd.row), r2 = Math.max(RB.selected.row, RB.rangeEnd.row);
  const c1 = Math.min(RB.selected.col, RB.rangeEnd.col), c2 = Math.max(RB.selected.col, RB.rangeEnd.col);
  return { r1, r2, c1, c2 };
}

function rbIsInRange(ri, ci) {
  const rect = rbSelectionRect();
  return !!rect && ri >= rect.r1 && ri <= rect.r2 && ci >= rect.c1 && ci <= rect.c2;
}

// ---------- Объединение ----------

function rbMergeSelection() {
  const sheet = rbCurSheet();
  const rect = rbSelectionRect();
  if (!rect) { notify('Выделите диапазон: кликните первую ячейку, затем Shift+клик по последней.', 'error'); return; }
  const { r1, r2, c1, c2 } = rect;
  if (r1 === r2 && c1 === c2) { notify('Выделите больше одной ячейки для объединения.', 'error'); return; }
  if (r2 > r1) {
    for (let ri = r1; ri <= r2; ri++) if (sheet.rows[ri].repeat) { notify('Нельзя объединять по вертикали через повторяющуюся строку.', 'error'); return; }
  }
  const anchorExisting = rbCellAt(sheet.rows[r1], c1);
  const toRemove = [];
  for (let ri = r1; ri <= r2; ri++) {
    for (const c of sheet.rows[ri].cells) {
      const within = c.col >= c1 && c.col + (c.colspan || 1) - 1 <= c2;
      if (within && !(ri === r1 && c.col === c1)) toRemove.push([ri, c]);
    }
  }
  if (toRemove.length && !confirm('Внутри диапазона есть другие ячейки с содержимым — они будут удалены при объединении. Продолжить?')) return;
  for (const [ri, c] of toRemove) { const row = sheet.rows[ri]; row.cells.splice(row.cells.indexOf(c), 1); }
  const anchor = anchorExisting || { col: c1, kind: 'static', text: '', style: {} };
  anchor.colspan = c2 - c1 + 1;
  anchor.rowspan = r2 - r1 + 1;
  if (!anchorExisting) sheet.rows[r1].cells.push(anchor);
  RB.selected = { sheet: RB.editor.activeSheet, row: r1, col: c1 };
  RB.rangeEnd = null;
  rbRenderGridEditor();
}

function rbUnmergeCell(ri, ci) {
  const cell = rbCellAt(rbCurSheet().rows[ri], ci);
  if (!cell) return;
  cell.colspan = 1; cell.rowspan = 1;
  rbRenderGridEditor();
}

// ---------- Содержимое ячейки ----------

function rbEnsureCell(ri, ci) {
  const sheet = rbCurSheet();
  let cell = rbCellAt(sheet.rows[ri], ci);
  if (!cell) { cell = { col: ci, kind: 'static', text: '', style: {} }; sheet.rows[ri].cells.push(cell); }
  return cell;
}

function rbSetCellKind(ri, ci, kind) {
  const row = rbCurSheet().rows[ri];
  if (kind !== 'static' && !row.repeat) {
    notify('Поле из БД, «№» и формула обычно нужны в повторяющейся строке — отметьте строку как повторяющуюся слева, в настройках строки.', 'info');
  }
  const cell = rbEnsureCell(ri, ci);
  cell.kind = kind;
  if (kind === 'field') { if (cell.path === undefined) cell.path = ''; if (cell.separator === undefined) cell.separator = '; '; delete cell.text; }
  if (kind === 'formula' && !cell.text) cell.text = '=';
  if (kind === 'static' && cell.text === undefined) cell.text = '';
  if (kind === 'index') { delete cell.path; delete cell.text; }
  rbRenderGridEditor();
}
function rbSetCellText(ri, ci, v) { rbEnsureCell(ri, ci).text = v; rbRenderGridEditor(); }
function rbSetCellPath(ri, ci, v) { rbEnsureCell(ri, ci).path = v; rbRenderGridEditor(); }
function rbSetCellSeparator(ri, ci, v) { rbEnsureCell(ri, ci).separator = v; }

function rbDeleteCell(ri, ci) {
  const row = rbCurSheet().rows[ri];
  const cell = rbCellAt(row, ci);
  if (!cell) return;
  row.cells.splice(row.cells.indexOf(cell), 1);
  rbRenderGridEditor();
}

function rbSetCellStyle(ri, ci, key, value) {
  const cell = rbEnsureCell(ri, ci);
  cell.style = cell.style || {};
  if (value === '' || value === null || value === false) delete cell.style[key]; else cell.style[key] = value;
  rbRenderGridEditor();
}

// ---------- Drag & drop полей из палитры ----------

function rbDragStart(ev, path, entity) {
  RB.dragField = { path, entity };
  if (ev && ev.dataTransfer) { ev.dataTransfer.effectAllowed = 'copy'; try { ev.dataTransfer.setData('text/plain', path); } catch (e) { /* jsdom/некоторые браузеры без полноценного DataTransfer */ } }
}
function rbDragSpecial(ev, kind) {
  RB.dragField = { special: kind };
  if (ev && ev.dataTransfer) ev.dataTransfer.effectAllowed = 'copy';
}

function rbDropOnCell(ev, ri, ci) {
  if (ev && ev.preventDefault) ev.preventDefault();
  const drag = RB.dragField;
  RB.dragField = null;
  if (!drag) return;
  const sheet = rbCurSheet();
  const row = sheet.rows[ri];

  if (drag.special === 'index') {
    if (!row.repeat) { notify('«№ строки» доступен только в повторяющейся строке — сначала включите повторение в настройках строки (⚙).', 'error'); return; }
    const cell = rbEnsureCell(ri, ci); cell.kind = 'index'; delete cell.path; delete cell.text;
    rbRenderGridEditor(); return;
  }
  if (drag.special === 'formula') {
    const cell = rbEnsureCell(ri, ci); cell.kind = 'formula'; if (!cell.text || !cell.text.startsWith('=')) cell.text = '=';
    rbRenderGridEditor(); return;
  }

  // Обычное поле БД: первое перетаскивание в строку автоматически включает повторение по её сущности.
  if (!row.repeat) {
    if (rbRowSpanCoverage(sheet, ri).size || row.cells.some(c => (c.rowspan || 1) > 1)) {
      notify('Эта строка задействована в вертикальном объединении — сначала разъедините ячейки.', 'error'); return;
    }
    row.repeat = true;
    row.data_source = { root_entity: drag.entity, expand: '', include_empty_expand: true, filters: [], sort_by: '' };
  } else if (!row.data_source.root_entity) {
    row.data_source.root_entity = drag.entity;
  } else if (row.data_source.root_entity !== drag.entity) {
    notify(`Эта строка уже привязана к сущности «${rbLabel(row.data_source.root_entity)}» — поле из другой сущности сюда перетащить нельзя. Создайте для него отдельную повторяющуюся строку.`, 'error');
    return;
  }
  const cell = rbEnsureCell(ri, ci);
  cell.kind = 'field'; cell.path = drag.path; if (cell.separator === undefined) cell.separator = '; ';
  delete cell.text;
  RB.paletteEntity = drag.entity;
  rbRenderGridEditor();
}

// ---------- Рендеринг: параметры, вкладки листов, палитра ----------

function rbAddParam() { RB.editor.params.push({ key: '', label: '', default: '' }); rbRenderGridEditor(); }
function rbRemoveParam(i) { RB.editor.params.splice(i, 1); rbRenderGridEditor(); }
function rbSetParam(i, key, v) { RB.editor.params[i][key] = v; }

function rbParamsHTML() {
  const params = RB.editor.params;
  return `<div class="panel">
    <div class="top" style="margin-bottom:8px"><h3 style="margin:0">Параметры отчёта</h3><button type="button" class="btn gray" onclick="rbAddParam()">+ Параметр</button></div>
    <div class="muted">Параметры пользователь вводит перед формированием файла — используйте их в тексте ячеек как <code>{{ключ}}</code>. Также доступен <code>{{report_date}}</code> — текущая дата.</div>
    <div class="nested-list">${params.map((p, i) => `<div class="nested-row rb-param-row">
      <input placeholder="ключ (латиницей)" value="${esc(p.key)}" onchange="rbSetParam(${i},'key',this.value)">
      <input placeholder="подпись" value="${esc(p.label)}" onchange="rbSetParam(${i},'label',this.value)">
      <input placeholder="значение по умолчанию" value="${esc(p.default)}" onchange="rbSetParam(${i},'default',this.value)">
      <button type="button" class="btn red" onclick="rbRemoveParam(${i})">✕</button>
    </div>`).join('') || '<div class="muted">Параметров нет</div>'}</div>
  </div>`;
}

function rbTabsHTML() {
  return `<div class="rbg-tabs">
    ${RB.editor.sheets.map((s, si) => `<button type="button" class="rbg-tab ${si === RB.editor.activeSheet ? 'active' : ''}" onclick="rbSwitchSheet(${si})">${esc(s.title || 'Лист')}</button>`).join('')}
    <button type="button" class="btn gray" onclick="rbAddSheet()">+ Лист</button>
    ${RB.editor.sheets.length > 1 ? `<button type="button" class="btn red" onclick="rbRemoveSheet(${RB.editor.activeSheet})">Удалить текущий лист</button>` : ''}
  </div>`;
}

function rbPaletteHTML() {
  const chips = RB.paletteEntity ? rbFlattenPaths(RB.paletteEntity) : [];
  return `<div class="rbg-palette">
    <h4>Палитра полей</h4>
    <div class="field"><label>Сущность</label><select onchange="RB.paletteEntity=this.value;rbRenderGridEditor()">${rbEntityOptionsHTML(RB.paletteEntity)}</select></div>
    <div class="muted" style="margin:6px 0;font-size:12px">Перетащите поле на ячейку листа. Первое поле, перетащенное в строку, включает для неё повторение по этой сущности.</div>
    <div class="rbg-special-chips">
      <div class="rbg-chip" draggable="true" ondragstart="rbDragSpecial(event,'index')" title="Порядковый номер записи в повторяющейся строке">🔢 № по порядку</div>
      <div class="rbg-chip" draggable="true" ondragstart="rbDragSpecial(event,'formula')" title="Формула Excel — вычисляется самим Excel при открытии файла">ƒ Формула</div>
    </div>
    <div class="rbg-chip-list">
      ${RB.paletteEntity ? (chips.length ? chips.map(f => `<div class="rbg-chip" draggable="true" ondragstart="rbDragStart(event,'${esc(f.path)}','${esc(RB.paletteEntity)}')" title="${esc(f.path)}">${esc(f.label)}</div>`).join('') : '<div class="muted">У сущности нет полей</div>') : '<div class="muted">Выберите сущность выше</div>'}
    </div>
  </div>`;
}

// ---------- Рендеринг: сетка листа ----------

function rbCellContentHTML(cell) {
  const kind = cell.kind || 'static';
  if (kind === 'index') return '<span class="rbg-badge">№</span>';
  if (kind === 'formula') return `<code>${esc(cell.text || '=')}</code>`;
  if (kind === 'field') return `<span class="rbg-badge field">поле</span>${esc(cell.path || '(не задан путь)')}`;
  return cell.text ? esc(cell.text) : '<span class="muted">…</span>';
}

function rbCellStyleCSS(style) {
  style = style || {};
  const parts = [];
  if (style.bold) parts.push('font-weight:700');
  if (style.italic) parts.push('font-style:italic');
  if (style.underline) parts.push('text-decoration:underline');
  parts.push(`text-align:${style.align || 'left'}`);
  parts.push(`vertical-align:${{ top: 'top', middle: 'middle', bottom: 'bottom' }[style.valign] || 'top'}`);
  if (style.bg) parts.push(`background:${style.bg}`);
  if (style.color) parts.push(`color:${style.color}`);
  if (style.wrap === false) parts.push('white-space:nowrap');
  return parts.join(';');
}

function rbCellTdHTML(si, ri, ci, cell) {
  const colspan = cell.colspan || 1, rowspan = cell.rowspan || 1;
  const isSel = RB.selected && RB.selected.sheet === si && RB.selected.row === ri && RB.selected.col === ci;
  const inRange = RB.selected && RB.selected.sheet === si && rbIsInRange(ri, ci) && !isSel;
  const cls = `rbg-cell${isSel ? ' selected' : ''}${inRange ? ' in-range' : ''}`;
  return `<td class="${cls}" style="${rbCellStyleCSS(cell.style)}" colspan="${colspan}" rowspan="${rowspan}"
    onclick="rbSelectCell(${si},${ri},${ci},event)"
    ondragover="event.preventDefault();this.classList.add('drag-over')" ondragleave="this.classList.remove('drag-over')"
    ondrop="this.classList.remove('drag-over');rbDropOnCell(event,${ri},${ci})">${rbCellContentHTML(cell)}</td>`;
}

function rbEmptyTdHTML(si, ri, ci) {
  const isSel = RB.selected && RB.selected.sheet === si && RB.selected.row === ri && RB.selected.col === ci;
  const inRange = RB.selected && RB.selected.sheet === si && rbIsInRange(ri, ci) && !isSel;
  const cls = `rbg-cell${isSel ? ' selected' : ''}${inRange ? ' in-range' : ''}`;
  return `<td class="${cls}"
    onclick="rbSelectCell(${si},${ri},${ci},event)"
    ondragover="event.preventDefault();this.classList.add('drag-over')" ondragleave="this.classList.remove('drag-over')"
    ondrop="this.classList.remove('drag-over');rbDropOnCell(event,${ri},${ci})"><span class="muted">·</span></td>`;
}

function rbRenderRowCells(sheet, si, ri) {
  const coverage = rbRowSpanCoverage(sheet, ri);
  const row = sheet.rows[ri];
  const nCols = sheet.columns.length;
  let html = '', col = 0;
  while (col < nCols) {
    if (coverage.has(col)) { col++; continue; }
    const cell = rbCellAt(row, col);
    if (cell) { html += rbCellTdHTML(si, ri, col, cell); col += (cell.colspan || 1); }
    else { html += rbEmptyTdHTML(si, ri, col); col++; }
  }
  return html;
}

function rbGridToolbarHTML() {
  const rect = rbSelectionRect();
  return `<div class="rbg-toggle-row">
    <button type="button" class="btn gray" onclick="rbMergeSelection()" ${rect ? '' : 'disabled'}>⛶ Объединить выделенное</button>
    <span class="muted" style="align-self:center">${rect ? `Выделено: ${rbColLetter(rect.c1)}${rect.r1 + 1}:${rbColLetter(rect.c2)}${rect.r2 + 1}` : 'Кликните ячейку, затем Shift+клик по другой — выделится диапазон для объединения'}</span>
  </div>`;
}

function rbGridHTML() {
  const si = RB.editor.activeSheet;
  const sheet = rbCurSheet();
  const nCols = sheet.columns.length;
  let html = `<div class="rbg-grid-wrap"><table class="rbg-grid"><thead><tr><th class="rbg-colhead"></th>`;
  for (let ci = 0; ci < nCols; ci++) {
    html += `<th class="rbg-colhead">${rbColLetter(ci)}<br><input type="number" min="4" value="${sheet.columns[ci].width}" onchange="rbSetColWidth(${ci},this.value)" title="Ширина колонки">${nCols > 1 ? ` <button type="button" class="btn red" title="Удалить колонку" onclick="rbRemoveColumn(${ci})">✕</button>` : ''}</th>`;
  }
  html += `<th class="rbg-colhead"><button type="button" class="btn gray" title="Добавить колонку" onclick="rbAddColumn()">+</button></th></tr></thead><tbody>`;
  sheet.rows.forEach((row, ri) => {
    const rowSel = RB.selected && RB.selected.sheet === si && RB.selected.row === ri && RB.selected.col === null;
    html += `<tr><th class="rbg-rowhead${rowSel ? ' selected' : ''}">
      <div class="rbg-rowhead-tools">
        <span title="${row.repeat ? 'Повторяющаяся строка' : 'Статическая строка'}">${ri + 1}${row.repeat ? ' 🔁' : ''}</span>
        <button type="button" class="btn gray" onclick="rbSelectRow(${si},${ri})" title="Настройки строки">⚙</button>
        <button type="button" class="btn gray" onclick="rbAddRowAt(${ri})" title="Вставить строку ниже">+</button>
        <button type="button" class="btn red" onclick="rbRemoveRow(${ri})" title="Удалить строку">✕</button>
        <input type="number" min="10" value="${row.height}" onchange="rbSetRowHeight(${ri},this.value)" title="Высота строки">
      </div>
    </th>${rbRenderRowCells(sheet, si, ri)}</tr>`;
  });
  html += `</tbody></table></div>`;
  return html;
}

// ---------- Рендеринг: инспектор (ячейка / строка) ----------

function rbInspectorHTML() {
  const si = RB.editor.activeSheet;
  const sel = RB.selected;
  if (!sel || sel.sheet !== si) {
    return `<div class="rbg-inspector"><h4>Инспектор</h4><div class="muted">Кликните ячейку, чтобы отредактировать её содержимое и стиль, или значок ⚙ у строки — чтобы настроить источник данных. Shift+клик по второй ячейке выделяет диапазон для объединения.</div></div>`;
  }
  const sheet = rbCurSheet();
  const row = sheet.rows[sel.row];
  return sel.col === null ? rbRowInspectorHTML(sel.row, row) : rbCellInspectorHTML(sel.row, sel.col, row);
}

function rbRowInspectorHTML(ri, row) {
  const ds = row.data_source || {};
  let html = `<div class="rbg-inspector"><h4>Строка ${ri + 1}</h4>
    <label style="display:flex;gap:6px;align-items:center;margin-bottom:10px;font-weight:400"><input type="checkbox" ${row.repeat ? 'checked' : ''} onchange="rbToggleRepeat(${ri})"> Повторяющаяся строка (клонируется по одной на запись)</label>`;
  if (row.repeat) {
    const sortId = `rb-sort-${ri}`;
    html += `<div class="field"><label>Сущность</label><select onchange="rbSetRowEntity(${ri},this.value)">${rbEntityOptionsHTML(ds.root_entity)}</select></div>
    <div class="field"><label>Циклический вывод по связи</label><select onchange="rbSetRowExpand(${ri},this.value)" ${!ds.root_entity ? 'disabled' : ''}>${rbExpandOptionsHTML(ds.root_entity, ds.expand)}</select></div>
    <label style="display:flex;gap:6px;align-items:center;font-weight:400;margin:8px 0"><input type="checkbox" ${ds.include_empty_expand ? 'checked' : ''} onchange="rbSetRowIncludeEmpty(${ri},this.checked)" ${!ds.expand ? 'disabled' : ''}> Выводить запись, даже если по связи нет данных</label>
    <div class="field"><label>Сортировка (необязательно)</label><div class="rbg-path-group"><input id="${sortId}" value="${esc(ds.sort_by || '')}" onchange="rbSetRowSort(${ri},this.value)">${rbFieldPickerHTML(ds.root_entity, sortId)}</div></div>
    <h4 style="margin-top:14px">Фильтры</h4>
    <div class="nested-list">${(ds.filters || []).map((f, fi) => {
      const pid = `rb-fpath-${ri}-${fi}`;
      return `<div class="nested-row rb-filter-row">
        <input id="${pid}" placeholder="путь поля" value="${esc(f.path)}" onchange="rbSetRowFilter(${ri},${fi},'path',this.value)">
        ${rbFieldPickerHTML(ds.root_entity, pid)}
        <select onchange="rbSetRowFilter(${ri},${fi},'op',this.value)">${RB_FILTER_OPS.map(([v, l]) => `<option value="${v}" ${f.op === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
        <input placeholder="значение" value="${esc(f.value)}" onchange="rbSetRowFilter(${ri},${fi},'value',this.value)" ${['not_empty', 'is_true', 'is_false'].includes(f.op) ? 'disabled' : ''}>
        <button type="button" class="btn red" onclick="rbRemoveRowFilter(${ri},${fi})">✕</button>
      </div>`;
    }).join('') || '<div class="muted">Фильтров нет — выводятся все записи</div>'}</div>
    <button type="button" class="btn gray" onclick="rbAddRowFilter(${ri})" ${!ds.root_entity ? 'disabled' : ''}>+ Фильтр</button>`;
  } else {
    html += `<div class="muted">Строка выводится один раз как есть — статический текст/формулы (заголовок, титул).</div>`;
  }
  html += `</div>`;
  return html;
}

function rbCellInspectorHTML(ri, ci, row) {
  const cell = rbCellAt(row, ci);
  const cellExists = !!cell;
  const c = cell || { kind: 'static', text: '', style: {} };
  const style = c.style || {};
  let html = `<div class="rbg-inspector"><h4>Ячейка ${rbColLetter(ci)}${ri + 1}</h4>`;
  if (!cellExists) html += `<div class="muted" style="margin-bottom:8px">Пустая ячейка — задайте тип содержимого или перетащите сюда поле.</div>`;
  html += `<div class="field"><label>Тип содержимого</label>
    <select onchange="rbSetCellKind(${ri},${ci},this.value)">
      <option value="static" ${(!c.kind || c.kind === 'static') ? 'selected' : ''}>Статический текст</option>
      <option value="field" ${c.kind === 'field' ? 'selected' : ''}>Поле из БД</option>
      <option value="index" ${c.kind === 'index' ? 'selected' : ''}>№ по порядку</option>
      <option value="formula" ${c.kind === 'formula' ? 'selected' : ''}>Формула Excel</option>
    </select></div>`;
  if (!c.kind || c.kind === 'static') {
    html += `<div class="field"><label>Текст (можно {{параметр}} и {{report_date}})</label><textarea onchange="rbSetCellText(${ri},${ci},this.value)">${esc(c.text || '')}</textarea></div>`;
  } else if (c.kind === 'field') {
    const pid = `rb-cellpath-${ri}-${ci}`;
    html += `<div class="field"><label>Путь поля</label><div class="rbg-path-group"><input id="${pid}" value="${esc(c.path || '')}" onchange="rbSetCellPath(${ri},${ci},this.value)">${rbFieldPickerHTML(row.data_source && row.data_source.root_entity, pid)}</div></div>
    <div class="field"><label>Разделитель (для полей-списков)</label><input value="${esc(c.separator ?? '; ')}" onchange="rbSetCellSeparator(${ri},${ci},this.value)"></div>`;
  } else if (c.kind === 'formula') {
    html += `<div class="field"><label>Формула (начинается с =, можно {{параметр}} и {{report_date}})</label><input value="${esc(c.text || '=')}" onchange="rbSetCellText(${ri},${ci},this.value)"></div>`;
  } else {
    html += `<div class="muted">№ записи внутри повторения — без дополнительных настроек.</div>`;
  }
  html += `<h4 style="margin-top:14px">Оформление</h4><div class="rbg-style-grid">
    <label><input type="checkbox" ${style.bold ? 'checked' : ''} onchange="rbSetCellStyle(${ri},${ci},'bold',this.checked)"> Жирный</label>
    <label><input type="checkbox" ${style.italic ? 'checked' : ''} onchange="rbSetCellStyle(${ri},${ci},'italic',this.checked)"> Курсив</label>
    <label><input type="checkbox" ${style.underline ? 'checked' : ''} onchange="rbSetCellStyle(${ri},${ci},'underline',this.checked)"> Подчёркнутый</label>
    <label><input type="checkbox" ${style.border ? 'checked' : ''} onchange="rbSetCellStyle(${ri},${ci},'border',this.checked)"> Рамка</label>
    <label><input type="checkbox" ${style.wrap === false ? '' : 'checked'} onchange="rbSetCellStyle(${ri},${ci},'wrap',this.checked)"> Перенос текста</label>
    <label>Выравнивание<select onchange="rbSetCellStyle(${ri},${ci},'align',this.value)"><option value="">по левому</option><option value="center" ${style.align === 'center' ? 'selected' : ''}>по центру</option><option value="right" ${style.align === 'right' ? 'selected' : ''}>по правому</option></select></label>
    <label>По вертикали<select onchange="rbSetCellStyle(${ri},${ci},'valign',this.value)"><option value="">сверху</option><option value="middle" ${style.valign === 'middle' ? 'selected' : ''}>по центру</option><option value="bottom" ${style.valign === 'bottom' ? 'selected' : ''}>снизу</option></select></label>
    <label>Фон<input type="color" value="${style.bg || '#ffffff'}" onchange="rbSetCellStyle(${ri},${ci},'bg',this.value)"></label>
    <label>Цвет текста<input type="color" value="${style.color || '#000000'}" onchange="rbSetCellStyle(${ri},${ci},'color',this.value)"></label>
    <label style="grid-column:1/-1">Числовой формат<select onchange="rbSetCellStyle(${ri},${ci},'number_format',this.value)">${RB_NUMBER_FORMATS.map(([v, l]) => `<option value="${v}" ${(style.number_format || '') === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
  </div>
  <div class="rbg-toggle-row">
    ${((c.colspan || 1) > 1 || (c.rowspan || 1) > 1) ? `<button type="button" class="btn gray" onclick="rbUnmergeCell(${ri},${ci})">Разъединить</button>` : ''}
    ${cellExists ? `<button type="button" class="btn red" onclick="rbDeleteCell(${ri},${ci})">Очистить ячейку</button>` : ''}
  </div></div>`;
  return html;
}

// ---------- Предпросмотр ----------

async function rbRunGridPreview() {
  try {
    const r = await get(api + '/report-builder/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'xlsx', config: rbCollectGridConfig(), limit: 15 }) });
    RB.preview = { sections: r.sections };
  } catch (e) { RB.preview = { error: errorMessage(e) }; }
  rbRenderGridEditor();
}

function rbPreviewRowsHTML(rows, nCols) {
  let html = '';
  rows.forEach((row, ri) => {
    const coverage = rbCoverageForRows(rows, ri);
    const byCol = Object.fromEntries(row.cells.map(c => [c.col, c]));
    let col = 0, rowHtml = '';
    while (col < nCols) {
      if (coverage.has(col)) { col++; continue; }
      const c = byCol[col];
      if (c) { rowHtml += `<td colspan="${c.colspan || 1}" rowspan="${c.rowspan || 1}" style="${rbCellStyleCSS(c.style)}">${esc(c.value ?? '')}</td>`; col += (c.colspan || 1); }
      else { rowHtml += `<td></td>`; col++; }
    }
    html += `<tr>${rowHtml}</tr>`;
  });
  return html;
}

function rbPreviewHTML() {
  if (!RB.preview) return '';
  if (RB.preview.error) return `<div class="panel"><h3>Предпросмотр</h3><div class="muted">Ошибка: ${esc(RB.preview.error)}</div></div>`;
  return `<div class="panel"><h3>Предпросмотр</h3>${RB.preview.sections.map(sec => {
    if (sec.error) return `<div class="muted">Лист «${esc(sec.title)}»: ошибка — ${esc(sec.error)}</div>`;
    return `<div style="margin-bottom:16px"><div class="muted">Лист «${esc(sec.title)}»${sec.total_records ? ` — показаны первые записи повторяющихся строк (до 15 из ${sec.total_records})` : ''}</div>
    <div class="tablewrap"><table class="rbg-preview-table"><tbody>${rbPreviewRowsHTML(sec.rows, sec.n_cols)}</tbody></table></div></div>`;
  }).join('')}</div>`;
}

// ---------- Сохранение ----------

async function rbSaveGridTemplate() {
  const e = RB.editor;
  if (!e.name.trim()) return notify('Укажите название шаблона.', 'error');
  const config = rbCollectGridConfig();
  const payload = { name: e.name.trim(), description: e.description || null, format: 'xlsx', config };
  try {
    const saved = e.id
      ? await get(api + `/report-templates/${e.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      : await get(api + '/report-templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    RB.editor.id = saved.id;
    notify('Шаблон сохранён.', 'success');
    rbRenderGridEditor();
  } catch (e2) { notifyError(e2); }
}

// ---------- Главный рендер экрана редактора ----------

function rbRenderGridEditor() {
  const e = RB.editor;
  const si = e.activeSheet;
  const content = document.getElementById('content');
  content.innerHTML = `<div class="top"><div><h2>${e.id ? 'Изменить шаблон' : 'Новый шаблон'} отчёта (Excel)</h2><div class="muted">Визуальный редактор листа — перетаскивайте поля из палитры прямо на лист</div></div>
    <div class="actions"><button class="btn gray" onclick="rbRunGridPreview()">👁 Предпросмотр</button> <button class="btn" onclick="rbSaveGridTemplate()">💾 Сохранить</button> <button class="btn gray" onclick="openReportBuilder()">Назад к списку</button></div></div>
  <div class="panel"><div class="formgrid">
    <div class="field"><label>Название шаблона</label><input value="${esc(e.name)}" onchange="RB.editor.name=this.value"></div>
    <div class="field full"><label>Описание</label><textarea onchange="RB.editor.description=this.value">${esc(e.description)}</textarea></div>
  </div></div>
  ${rbParamsHTML()}
  <div class="panel">
    ${rbTabsHTML()}
    <div class="field" style="max-width:320px;margin-bottom:10px"><label>Название листа</label><input value="${esc(rbCurSheet().title)}" onchange="rbSetSheetTitle(${si},this.value)"></div>
    ${rbGridToolbarHTML()}
    <div class="rbg-workspace">
      ${rbPaletteHTML()}
      ${rbGridHTML()}
      ${rbInspectorHTML()}
    </div>
  </div>
  ${rbPreviewHTML()}
  <div class="actions"><button class="btn" onclick="rbSaveGridTemplate()">💾 Сохранить шаблон</button></div>`;
}
