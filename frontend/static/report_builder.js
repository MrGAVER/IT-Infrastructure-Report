/*
 * Конструктор произвольных отчётов (xlsx/docx) — отдельный модуль, подключаемый после app.js.
 * Переиспользует общие хелперы app.js: api, get(), esc(), errorMessage(), showDashboard()
 * и общие CSS-классы (.btn/.panel/.modal/.dialog/.formgrid/.field/.nested-row).
 */
const RB = { entities: [], entitiesByKey: {}, templates: [], editor: null, preview: {} };

const RB_FILTER_OPS = [
  ['eq', 'равно'], ['ne', 'не равно'], ['contains', 'содержит'], ['not_contains', 'не содержит'],
  ['not_empty', 'не пусто'], ['is_true', 'да/включено'], ['is_false', 'нет/выключено'],
];

async function rbLoadEntities() {
  if (RB.entities.length) return;
  RB.entities = await get(api + '/report-builder/entities');
  RB.entitiesByKey = Object.fromEntries(RB.entities.map(e => [e.key, e]));
}

function rbLabel(entityKey) { return RB.entitiesByKey[entityKey]?.label || entityKey; }

// Строит плоский список путей полей до 2 связей вглубь (field / relation.field /
// relation[].relation2.field), для выпадающего списка-помощника рядом с текстовым полем пути.
// Ровно один сегмент "[]" на путь — то же ограничение, что и в report_engine.py.
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
    for (const rel of info.to_one) {
      walk(rel.target, [...segs, rel.name], [...labels, rbLabel(rel.target)], hops + 1, manyUsed);
    }
    if (!manyUsed) {
      for (const rel of info.to_many) {
        walk(rel.target, [...segs, rel.name + '[]'], [...labels, rbLabel(rel.target) + ' (список)'], hops + 1, true);
      }
    }
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
  return `<select class="rb-field-picker" onchange="if(this.value){document.getElementById('${targetInputId}').value=this.value;document.getElementById('${targetInputId}').dispatchEvent(new Event('input'));this.selectedIndex=0;}">
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
  content.innerHTML = `<div class="top"><div><h2>🧩 Конструктор отчётов</h2><div class="muted">Произвольные отчёты xlsx/docx на основе данных реестра — настраиваемые поля, фильтры и циклический вывод</div></div><div class="actions"><button class="btn" onclick="rbNewTemplate('xlsx')">+ Новый Excel-шаблон</button> <button class="btn gray" onclick="rbNewTemplate('docx')">+ Новый Word-шаблон</button> <button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div>
  <div class="panel"><div class="tablewrap"><table><thead><tr><th>Название</th><th>Формат</th><th>Описание</th><th>Изменён</th><th>Действия</th></tr></thead><tbody>
  ${RB.templates.length ? RB.templates.map(t => `<tr>
    <td><b>${esc(t.name)}</b></td>
    <td>${t.format === 'docx' ? 'Word (.docx)' : 'Excel (.xlsx)'}</td>
    <td class="muted">${esc(t.description || '')}</td>
    <td class="muted">${t.updated_at ? new Date(t.updated_at).toLocaleString('ru-RU') : ''}</td>
    <td>
      <button class="btn gray" onclick="rbEditTemplate('${t.id}')">Изменить</button>
      <button class="btn" onclick="rbGenerateTemplate('${t.id}')">Сформировать</button>
      <button class="btn gray" onclick="rbDuplicateTemplate('${t.id}')">Дублировать</button>
      <button class="btn red" onclick="rbDeleteTemplate('${t.id}')">Удалить</button>
    </td>
  </tr>`).join('') : `<tr><td colspan="5" class="muted">Пока нет ни одного шаблона отчёта — создайте первый кнопкой выше.</td></tr>`}
  </tbody></table></div></div>`;
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

// ---------- Редактор шаблона ----------

function rbNewTemplate(format) {
  RB.editor = { id: '', name: '', description: '', format, params: [], sheets: format === 'xlsx' ? [rbNewSheet()] : [], blocks: format === 'docx' ? [rbNewBlock('heading')] : [] };
  RB.preview = {};
  rbRenderEditor();
}

async function rbEditTemplate(id) {
  const t = await get(api + `/report-templates/${id}`);
  const cfg = t.config || {};
  RB.editor = {
    id: t.id, name: t.name, description: t.description || '', format: t.format,
    params: cfg.params || [], sheets: cfg.sheets || [], blocks: cfg.blocks || [],
  };
  if (RB.editor.format === 'xlsx' && !RB.editor.sheets.length) RB.editor.sheets.push(rbNewSheet());
  if (RB.editor.format === 'docx' && !RB.editor.blocks.length) RB.editor.blocks.push(rbNewBlock('heading'));
  RB.preview = {};
  rbRenderEditor();
}

function rbNewSheet() { return { title: 'Новый лист', root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '', columns: [rbNewColumn()] }; }
function rbNewColumn() { return { header: '', source: 'field', path: '', separator: '; ', value: '' }; }
function rbNewFilter() { return { path: '', op: 'eq', value: '' }; }
function rbNewBlock(type) {
  if (type === 'table') return { type: 'table', root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '', columns: [rbNewColumn()] };
  if (type === 'paragraph') return { type: 'paragraph', text: '' };
  if (type === 'page_break') return { type: 'page_break' };
  return { type: 'heading', level: 1, text: '' };
}

function rbSetFormat(fmt) {
  RB.editor.format = fmt;
  if (fmt === 'xlsx' && !RB.editor.sheets.length) RB.editor.sheets.push(rbNewSheet());
  if (fmt === 'docx' && !RB.editor.blocks.length) RB.editor.blocks.push(rbNewBlock('heading'));
  rbRenderEditor();
}

function rbAddParam() { RB.editor.params.push({ key: '', label: '', default: '' }); rbRenderEditor(); }
function rbRemoveParam(i) { RB.editor.params.splice(i, 1); rbRenderEditor(); }

function rbAddSheet() { RB.editor.sheets.push(rbNewSheet()); rbRenderEditor(); }
function rbRemoveSheet(i) { if (!confirm('Удалить лист?')) return; RB.editor.sheets.splice(i, 1); rbRenderEditor(); }
function rbAddBlock(type) { RB.editor.blocks.push(rbNewBlock(type)); rbRenderEditor(); }
function rbRemoveBlock(i) { if (!confirm('Удалить блок?')) return; RB.editor.blocks.splice(i, 1); rbRenderEditor(); }
function rbMoveBlock(i, dir) { const b = RB.editor.blocks; const j = i + dir; if (j < 0 || j >= b.length) return; [b[i], b[j]] = [b[j], b[i]]; rbRenderEditor(); }

function rbAddColumn(list) { list.columns.push(rbNewColumn()); rbRenderEditor(); }
function rbRemoveColumn(list, i) { list.columns.splice(i, 1); rbRenderEditor(); }
function rbMoveColumn(list, i, dir) { const c = list.columns; const j = i + dir; if (j < 0 || j >= c.length) return; [c[i], c[j]] = [c[j], c[i]]; rbRenderEditor(); }
function rbAddFilter(list) { list.filters.push(rbNewFilter()); rbRenderEditor(); }
function rbRemoveFilter(list, i) { list.filters.splice(i, 1); rbRenderEditor(); }

function rbColumnRowHTML(list, listPath, col, ci) {
  const pathInputId = `rb-path-${listPath}-${ci}`;
  return `<div class="nested-row rb-col-row">
    <input placeholder="Заголовок колонки" value="${esc(col.header)}" oninput="${listPath}.columns[${ci}].header=this.value">
    <select onchange="${listPath}.columns[${ci}].source=this.value;rbRenderEditor()">
      <option value="field" ${col.source === 'field' ? 'selected' : ''}>Поле из БД</option>
      <option value="static" ${col.source === 'static' ? 'selected' : ''}>Статический текст / параметр</option>
      <option value="index" ${col.source === 'index' ? 'selected' : ''}>№ строки по порядку</option>
    </select>
    ${col.source === 'field' ? `<div class="rb-path-group">
        <input id="${pathInputId}" placeholder="например name или vms[].name" value="${esc(col.path)}" oninput="${listPath}.columns[${ci}].path=this.value">
        ${rbFieldPickerHTML(list.root_entity, pathInputId)}
        <input class="rb-sep" placeholder="разделитель" title="Разделитель значений для полей-списков" value="${esc(col.separator ?? '; ')}" oninput="${listPath}.columns[${ci}].separator=this.value">
      </div>` : ''}
    ${col.source === 'static' ? `<input placeholder="Текст, можно {{параметр}} и {{report_date}}" value="${esc(col.value)}" oninput="${listPath}.columns[${ci}].value=this.value">` : ''}
    <div class="rb-row-actions">
      <button type="button" class="btn gray" title="Вверх" ${ci === 0 ? 'disabled' : ''} onclick="rbMoveColumn(${listPath},${ci},-1)">↑</button>
      <button type="button" class="btn gray" title="Вниз" ${ci === list.columns.length - 1 ? 'disabled' : ''} onclick="rbMoveColumn(${listPath},${ci},1)">↓</button>
      <button type="button" class="btn red" onclick="rbRemoveColumn(${listPath},${ci})">✕</button>
    </div>
  </div>`;
}

function rbFilterRowHTML(list, listPath, f, fi) {
  const pathInputId = `rb-fpath-${listPath}-${fi}`;
  return `<div class="nested-row rb-filter-row">
    <input id="${pathInputId}" placeholder="путь поля" value="${esc(f.path)}" oninput="${listPath}.filters[${fi}].path=this.value">
    ${rbFieldPickerHTML(list.root_entity, pathInputId)}
    <select onchange="${listPath}.filters[${fi}].op=this.value">${RB_FILTER_OPS.map(([v, l]) => `<option value="${v}" ${f.op === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
    <input placeholder="значение" value="${esc(f.value)}" oninput="${listPath}.filters[${fi}].value=this.value" ${['not_empty', 'is_true', 'is_false'].includes(f.op) ? 'disabled' : ''}>
    <button type="button" class="btn red" onclick="rbRemoveFilter(${listPath},${fi})">✕</button>
  </div>`;
}

// Общий редактор "источник данных таблицы" — переиспользуется и листом xlsx, и блоком-таблицей docx.
function rbTableConfigHTML(list, listPath) {
  const sortInputId = `rb-sort-${listPath}`;
  return `
  <div class="formgrid">
    <div class="field"><label>Исходная сущность (что перечисляем)</label>
      <select onchange="${listPath}.root_entity=this.value;${listPath}.expand='';rbRenderEditor()">${rbEntityOptionsHTML(list.root_entity)}</select>
    </div>
    <div class="field"><label>Циклический вывод по связи (несколько строк на запись)</label>
      <select onchange="${listPath}.expand=this.value;rbRenderEditor()" ${!list.root_entity ? 'disabled' : ''}>${rbExpandOptionsHTML(list.root_entity, list.expand)}</select>
    </div>
    <div class="field"><label>Сортировка по полю (необязательно)</label>
      <div class="rb-path-group"><input id="${sortInputId}" placeholder="например name" value="${esc(list.sort_by || '')}" oninput="${listPath}.sort_by=this.value">${rbFieldPickerHTML(list.root_entity, sortInputId)}</div>
    </div>
    <div class="field"><label>&nbsp;</label>
      <label style="font-weight:400"><input type="checkbox" ${list.include_empty_expand ? 'checked' : ''} onchange="${listPath}.include_empty_expand=this.checked" ${!list.expand ? 'disabled' : ''}> Выводить запись, даже если по связи нет данных</label>
    </div>
  </div>
  <h4>Фильтры (опционально — сузить выборку)</h4>
  <div class="nested-list">${list.filters.map((f, fi) => rbFilterRowHTML(list, listPath, f, fi)).join('') || '<div class="muted">Фильтров нет — выводятся все записи</div>'}</div>
  <button type="button" class="btn gray" onclick="rbAddFilter(${listPath})" ${!list.root_entity ? 'disabled' : ''}>+ Фильтр</button>
  <h4>Колонки</h4>
  <div class="nested-list">${list.columns.map((c, ci) => rbColumnRowHTML(list, listPath, c, ci)).join('')}</div>
  <button type="button" class="btn gray" onclick="rbAddColumn(${listPath})" ${!list.root_entity ? 'disabled' : ''}>+ Колонка</button>
  `;
}

function rbSheetCardHTML(sheet, si) {
  const listPath = `RB.editor.sheets[${si}]`;
  return `<div class="panel rb-block-card">
    <div class="rb-block-head">
      <input class="rb-title-input" placeholder="Название листа" value="${esc(sheet.title)}" oninput="${listPath}.title=this.value">
      <div>
        <button type="button" class="btn gray" onclick="rbPreviewSheet(${si})">👁 Предпросмотр</button>
        <button type="button" class="btn red" onclick="rbRemoveSheet(${si})">Удалить лист</button>
      </div>
    </div>
    ${rbTableConfigHTML(sheet, listPath)}
    ${rbPreviewBlockHTML('sheet-' + si)}
  </div>`;
}

function rbBlockCardHTML(block, bi) {
  const listPath = `RB.editor.blocks[${bi}]`;
  const typeLabels = { heading: 'Заголовок', paragraph: 'Абзац текста', table: 'Таблица данных', page_break: 'Разрыв страницы' };
  let body = '';
  if (block.type === 'heading') {
    body = `<div class="formgrid">
      <div class="field"><label>Уровень заголовка</label><select onchange="${listPath}.level=+this.value">${[1, 2, 3, 4].map(l => `<option value="${l}" ${block.level === l ? 'selected' : ''}>Заголовок ${l}</option>`).join('')}</select></div>
      <div class="field full"><label>Текст (можно {{параметр}} и {{report_date}})</label><input value="${esc(block.text)}" oninput="${listPath}.text=this.value"></div>
    </div>`;
  } else if (block.type === 'paragraph') {
    body = `<div class="field full"><label>Текст (можно {{параметр}} и {{report_date}})</label><textarea oninput="${listPath}.text=this.value">${esc(block.text)}</textarea></div>`;
  } else if (block.type === 'table') {
    body = `<div class="rb-block-head" style="margin-bottom:8px"><span></span><button type="button" class="btn gray" onclick="rbPreviewBlock(${bi})">👁 Предпросмотр</button></div>` + rbTableConfigHTML(block, listPath) + rbPreviewBlockHTML('block-' + bi);
  } else if (block.type === 'page_break') {
    body = `<div class="muted">Разрыв страницы — без настроек</div>`;
  }
  return `<div class="panel rb-block-card">
    <div class="rb-block-head">
      <b>${bi + 1}. ${esc(typeLabels[block.type] || block.type)}</b>
      <div>
        <button type="button" class="btn gray" title="Выше" ${bi === 0 ? 'disabled' : ''} onclick="rbMoveBlock(${bi},-1)">↑</button>
        <button type="button" class="btn gray" title="Ниже" ${bi === RB.editor.blocks.length - 1 ? 'disabled' : ''} onclick="rbMoveBlock(${bi},1)">↓</button>
        <button type="button" class="btn red" onclick="rbRemoveBlock(${bi})">Удалить блок</button>
      </div>
    </div>
    ${body}
  </div>`;
}

function rbPreviewBlockHTML(key) {
  const p = RB.preview[key];
  if (!p) return '';
  if (p.error) return `<div class="muted rb-preview">Ошибка предпросмотра: ${esc(p.error)}</div>`;
  return `<div class="rb-preview"><div class="muted">Предпросмотр — показаны первые ${p.rows.length} из ${p.total} строк</div>
    <div class="tablewrap"><table><thead><tr>${p.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${p.rows.map(r => `<tr>${r.map(v => `<td>${esc(v ?? '')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${p.headers.length}" class="muted">Нет данных, удовлетворяющих фильтрам</td></tr>`}</tbody></table></div></div>`;
}

function rbCollectConfig() {
  const e = RB.editor;
  const config = { params: e.params.filter(p => p.key) };
  if (e.format === 'xlsx') config.sheets = e.sheets;
  else config.blocks = e.blocks;
  return config;
}

async function rbPreviewSheet(si) { await rbRunPreview({ sheets: [RB.editor.sheets[si]] }, 'sheet-' + si); }
async function rbPreviewBlock(bi) { await rbRunPreview({ sheets: [RB.editor.blocks[bi]] }, 'block-' + bi); }

async function rbRunPreview(partialConfig, key) {
  try {
    const r = await get(api + '/report-builder/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'xlsx', config: partialConfig, limit: 15 }) });
    RB.preview[key] = r.sections[0];
  } catch (e) { RB.preview[key] = { error: errorMessage(e) }; }
  rbRenderEditor();
}

async function rbPreviewAllTables() {
  const e = RB.editor;
  if (e.format === 'xlsx') { for (let i = 0; i < e.sheets.length; i++) await rbRunPreview({ sheets: [e.sheets[i]] }, 'sheet-' + i); return; }
  for (let i = 0; i < e.blocks.length; i++) if (e.blocks[i].type === 'table') await rbRunPreview({ sheets: [e.blocks[i]] }, 'block-' + i);
}

function rbRenderEditor() {
  const e = RB.editor;
  const content = document.getElementById('content');
  content.innerHTML = `<div class="top"><div><h2>${e.id ? 'Изменить шаблон' : 'Новый шаблон'} отчёта</h2><div class="muted">Формат: ${e.format === 'docx' ? 'Word (.docx)' : 'Excel (.xlsx)'}</div></div>
    <div class="actions"><button class="btn gray" onclick="rbPreviewAllTables()">👁 Обновить предпросмотр</button> <button class="btn" onclick="rbSaveTemplate()">💾 Сохранить</button> <button class="btn gray" onclick="openReportBuilder()">Назад к списку</button></div></div>
  <div class="panel">
    <div class="formgrid">
      <div class="field"><label>Название шаблона</label><input value="${esc(e.name)}" oninput="RB.editor.name=this.value"></div>
      <div class="field"><label>Формат вывода</label><select onchange="rbSetFormat(this.value)" ${e.id ? 'disabled title="Формат нельзя изменить у сохранённого шаблона — создайте новый"' : ''}>
        <option value="xlsx" ${e.format === 'xlsx' ? 'selected' : ''}>Excel (.xlsx)</option>
        <option value="docx" ${e.format === 'docx' ? 'selected' : ''}>Word (.docx)</option>
      </select></div>
      <div class="field full"><label>Описание</label><textarea oninput="RB.editor.description=this.value">${esc(e.description)}</textarea></div>
    </div>
  </div>
  <div class="panel">
    <div class="rb-block-head"><h3 style="margin:0">Параметры отчёта</h3><button type="button" class="btn gray" onclick="rbAddParam()">+ Параметр</button></div>
    <div class="muted">Параметры пользователь вводит перед формированием файла — используйте их в тексте как <code>{{ключ}}</code>. Также всегда доступен <code>{{report_date}}</code> — текущая дата.</div>
    <div class="nested-list">${e.params.map((p, i) => `<div class="nested-row rb-param-row">
      <input placeholder="ключ (латиницей, без пробелов)" value="${esc(p.key)}" oninput="RB.editor.params[${i}].key=this.value">
      <input placeholder="подпись для пользователя" value="${esc(p.label)}" oninput="RB.editor.params[${i}].label=this.value">
      <input placeholder="значение по умолчанию" value="${esc(p.default)}" oninput="RB.editor.params[${i}].default=this.value">
      <button type="button" class="btn red" onclick="rbRemoveParam(${i})">✕</button>
    </div>`).join('') || '<div class="muted">Параметров нет</div>'}</div>
  </div>
  ${e.format === 'xlsx' ? `
    <div class="rb-block-head"><h3>Листы Excel</h3><button type="button" class="btn" onclick="rbAddSheet()">+ Лист</button></div>
    ${e.sheets.map((s, si) => rbSheetCardHTML(s, si)).join('')}
  ` : `
    <div class="rb-block-head"><h3>Блоки документа Word</h3>
      <div><button type="button" class="btn gray" onclick="rbAddBlock('heading')">+ Заголовок</button> <button type="button" class="btn gray" onclick="rbAddBlock('paragraph')">+ Абзац</button> <button type="button" class="btn gray" onclick="rbAddBlock('table')">+ Таблица</button> <button type="button" class="btn gray" onclick="rbAddBlock('page_break')">+ Разрыв страницы</button></div>
    </div>
    ${e.blocks.map((b, bi) => rbBlockCardHTML(b, bi)).join('')}
  `}
  <div class="actions"><button class="btn" onclick="rbSaveTemplate()">💾 Сохранить шаблон</button></div>`;
}

async function rbSaveTemplate() {
  const e = RB.editor;
  if (!e.name.trim()) return notify('Укажите название шаблона.','error');
  const config = rbCollectConfig();
  const payload = { name: e.name.trim(), description: e.description || null, format: e.format, config };
  try {
    const saved = e.id
      ? await get(api + `/report-templates/${e.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      : await get(api + '/report-templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    RB.editor.id = saved.id;
    notify('Шаблон сохранён.','success');
    rbRenderEditor();
  } catch (e2) { notifyError(e2); }
}
