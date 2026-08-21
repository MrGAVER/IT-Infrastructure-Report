'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadAppWindow } = require('./load-app.js');

// Значения из другого vm-realm не проходят строгую deepStrictEqual по прототипу с обычными
// объектами Node.js — см. то же примечание в app.smoke.test.js.
const plain = (v) => JSON.parse(JSON.stringify(v));

function fetchStub(handlers) {
  return (url) => {
    const key = Object.keys(handlers).find((k) => String(url).includes(k));
    const body = key ? handlers[key] : {};
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)),
    });
  };
}

test('openStructuralUnitsModal(): при отсутствии структурных единиц в базе сразу возвращает null, без показа модалки', async () => {
  const win = loadAppWindow({ fetchImpl: fetchStub({ '/resources/structural-units': { items: [] } }) });
  const result = await win.openStructuralUnitsModal();
  assert.equal(result, null);
  assert.equal(win.document.getElementById('structuralUnitsModal').classList.contains('show'), false);
});

test('openStructuralUnitsModal(): рендерит единицы с отступом по глубине parent_id (родитель перед потомком)', async () => {
  const win = loadAppWindow({
    fetchImpl: fetchStub({
      '/resources/structural-units': {
        items: [
          { id: 'child', name: 'Филиал (вложенный)', parent_id: 'parent' },
          { id: 'parent', name: 'Головной офис', parent_id: null },
        ],
      },
    }),
  });
  const pending = win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(win.document.getElementById('structuralUnitsModal').classList.contains('show'), true);
  const items = [...win.document.querySelectorAll('#suUnitList label')];
  assert.deepEqual(items.map((el) => el.textContent.trim()), ['Головной офис', 'Филиал (вложенный)']);
  assert.match(items[0].getAttribute('style') || '', /padding-left:0px/);
  assert.match(items[1].getAttribute('style'), /padding-left:20px/);
  win.closeStructuralUnitsModal();
  assert.equal(await pending, undefined);
});

test('closeStructuralUnitsModal(): разрешает промис в undefined (отмена формирования отчёта целиком)', async () => {
  const win = loadAppWindow({ fetchImpl: fetchStub({ '/resources/structural-units': { items: [{ id: 'u1', name: 'Единица' }] } }) });
  const pending = win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.closeStructuralUnitsModal();
  assert.equal(await pending, undefined);
  assert.equal(win.document.getElementById('structuralUnitsModal').classList.contains('show'), false);
});

test('confirmStructuralUnitsModal(): режим "Всё оборудование" (по умолчанию) разрешает промис в null', async () => {
  const win = loadAppWindow({ fetchImpl: fetchStub({ '/resources/structural-units': { items: [{ id: 'u1', name: 'Единица' }] } }) });
  const pending = win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.confirmStructuralUnitsModal();
  assert.equal(await pending, null);
});

test('confirmStructuralUnitsModal(): режим "Выбрать" без отмеченных единиц не закрывает модалку и предупреждает', async () => {
  const win = loadAppWindow({ fetchImpl: fetchStub({ '/resources/structural-units': { items: [{ id: 'u1', name: 'Единица' }] } }) });
  win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.document.querySelector('input[name="su-mode"][value="select"]').checked = true;
  win.confirmStructuralUnitsModal();
  assert.equal(win.document.getElementById('structuralUnitsModal').classList.contains('show'), true);
  assert.ok(win.document.querySelector('#toast-container .toast.error'));
});

test('confirmStructuralUnitsModal(): режим "Выбрать" с отмеченными единицами разрешает промис в их id', async () => {
  const win = loadAppWindow({
    fetchImpl: fetchStub({
      '/resources/structural-units': { items: [{ id: 'u1', name: 'Единица 1' }, { id: 'u2', name: 'Единица 2' }] },
    }),
  });
  const pending = win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.document.querySelector('input[name="su-mode"][value="select"]').checked = true;
  win._suToggleMode();
  assert.equal(win.document.getElementById('suUnitList').style.display, '');
  win.document.querySelector('.su-checkbox[value="u1"]').checked = true;
  win.confirmStructuralUnitsModal();
  assert.deepEqual(plain(await pending), ['u1']);
});

test('_suSetAll(): отмечает и снимает все чекбоксы единиц разом', async () => {
  const win = loadAppWindow({
    fetchImpl: fetchStub({
      '/resources/structural-units': { items: [{ id: 'u1', name: 'Единица 1' }, { id: 'u2', name: 'Единица 2' }] },
    }),
  });
  win.openStructuralUnitsModal();
  await new Promise((resolve) => setTimeout(resolve, 20));
  win._suSetAll(true);
  assert.deepEqual([...win.document.querySelectorAll('.su-checkbox')].map((c) => c.checked), [true, true]);
  win._suSetAll(false);
  assert.deepEqual([...win.document.querySelectorAll('.su-checkbox')].map((c) => c.checked), [false, false]);
});

test('generateReport(): без структурных единиц в базе отправляет POST со structural_unit_ids=null (полный отчёт, как раньше)', async () => {
  const calls = [];
  const win = loadAppWindow({
    fetchImpl: (url, opt) => {
      calls.push({ url: String(url), opt });
      const body = String(url).includes('/resources/structural-units') ? { items: [] } :
        String(url).includes('/reports/inventory') ? { file_name: 'r.xlsx', download_url: '/dl/r.xlsx' } : {};
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });
    },
  });
  const btn = win.document.createElement('button');
  btn.textContent = 'Сформировать Excel';
  await win.generateReport(btn);
  const reportCall = calls.find((c) => c.url.includes('/reports/inventory'));
  assert.ok(reportCall, 'должен быть POST-запрос на /reports/inventory');
  assert.equal(reportCall.opt.method, 'POST');
  assert.deepEqual(JSON.parse(reportCall.opt.body), { structural_unit_ids: null });
});

test('generateReport(): пользователь отменяет выбор структурной единицы — запрос на генерацию не отправляется', async () => {
  const calls = [];
  const win = loadAppWindow({
    fetchImpl: (url, opt) => {
      calls.push(String(url));
      const body = String(url).includes('/resources/structural-units') ? { items: [{ id: 'u1', name: 'Единица' }] } : {};
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });
    },
  });
  const btn = win.document.createElement('button');
  const call = win.generateReport(btn);
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.closeStructuralUnitsModal();
  await call;
  assert.ok(!calls.some((u) => u.includes('/reports/inventory')), 'генерация не должна была вызываться после отмены');
});

test('generateReport(): выбор конкретной структурной единицы передаёт её id в теле запроса', async () => {
  const calls = [];
  const win = loadAppWindow({
    fetchImpl: (url, opt) => {
      calls.push({ url: String(url), opt });
      const body = String(url).includes('/resources/structural-units') ? { items: [{ id: 'u1', name: 'Филиал А' }] } :
        String(url).includes('/reports/inventory') ? { file_name: 'r.xlsx', download_url: '/dl/r.xlsx' } : {};
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });
    },
  });
  const btn = win.document.createElement('button');
  const call = win.generateReport(btn);
  await new Promise((resolve) => setTimeout(resolve, 20));
  win.document.querySelector('input[name="su-mode"][value="select"]').checked = true;
  win.document.querySelector('.su-checkbox[value="u1"]').checked = true;
  win.confirmStructuralUnitsModal();
  await call;
  const reportCall = calls.find((c) => c.url.includes('/reports/inventory'));
  assert.deepEqual(JSON.parse(reportCall.opt.body), { structural_unit_ids: ['u1'] });
});

test('fieldLabel(): различает подпись parent_id между departments и structural-units — общий labels{} их не различает по имени поля', () => {
  const win = loadAppWindow();
  win.eval('resource = "departments"');
  assert.equal(win.fieldLabel({ name: 'parent_id' }), 'Родительское подразделение');
  win.eval('resource = "structural-units"');
  assert.equal(win.fieldLabel({ name: 'parent_id' }), 'Родительская структурная единица');
  assert.equal(win.fieldLabel({ name: 'name' }), 'Наименование');
});

test('openQuickModal("structural-units", ...): резолвит parent_id в саму структурную единицу, не в departments (см. fieldLabel/map fix)', async () => {
  const requestedUrls = [];
  const win = loadAppWindow({
    fetchImpl: (url) => {
      requestedUrls.push(String(url));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }), text: () => Promise.resolve('{"items":[]}') });
    },
  });
  await win.openQuickModal('structural-units', 'structural_unit_id');
  assert.ok(requestedUrls.some((u) => u.includes('/resources/structural-units?limit=1000')),
    'поле parent_id справочника structural-units должно предлагать варианты из structural-units');
  assert.ok(!requestedUrls.some((u) => u.includes('/resources/departments?limit=1000')),
    'поле parent_id справочника structural-units не должно путаться со справочником departments');
});

test('openQuickModal("departments", ...): по-прежнему резолвит свой parent_id в departments (регресс после фикса для structural-units)', async () => {
  const requestedUrls = [];
  const win = loadAppWindow({
    fetchImpl: (url) => {
      requestedUrls.push(String(url));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }), text: () => Promise.resolve('{"items":[]}') });
    },
  });
  await win.openQuickModal('departments', 'parent_id');
  assert.ok(requestedUrls.some((u) => u.includes('/resources/departments?limit=1000')));
});

test('_templateUsesRegistryEntities(): true если хотя бы одна повторяющаяся строка xlsx-шаблона использует "виртуальную" сущность реестра', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  const cfgWith = { sheets: [{ rows: [{ repeat: true, data_source: { root_entity: 'registry-device-rows' } }] }] };
  assert.equal(win._templateUsesRegistryEntities(cfgWith), true);
  const cfgWithout = { sheets: [{ rows: [{ repeat: true, data_source: { root_entity: 'devices' } }] }] };
  assert.equal(win._templateUsesRegistryEntities(cfgWithout), false);
});

test('_templateUsesRegistryEntities(): проверяет docx-блоки (root_entity на самом блоке, не data_source)', () => {
  const win = loadAppWindow({ withReportBuilder: true });
  const cfgWith = { blocks: [{ type: 'table', root_entity: 'registry-is-rows' }] };
  assert.equal(win._templateUsesRegistryEntities(cfgWith), true);
  const cfgWithout = { blocks: [{ type: 'heading' }, { type: 'table', root_entity: 'vms' }] };
  assert.equal(win._templateUsesRegistryEntities(cfgWithout), false);
  assert.equal(win._templateUsesRegistryEntities({}), false);
});
