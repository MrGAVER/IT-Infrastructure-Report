'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadAppWindow } = require('./load-app.js');

// Значения, созданные внутри jsdom vm-контекста (другой JS-realm), не проходят строгую
// deepStrictEqual по прототипу с обычными объектами/массивами Node.js, даже если структурно
// идентичны ("same structure but are not reference-equal"). JSON-круговорот убирает разницу
// realm'ов там, где сравниваются простые данные (массивы строк и т.п.).
const plain = (v) => JSON.parse(JSON.stringify(v));

test('esc() экранирует HTML-спецсимволы', () => {
  const win = loadAppWindow();
  assert.equal(win.esc('<b>&"x"</b>'), '&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;');
});

test('esc() не падает на null/undefined — превращает их в пустую строку', () => {
  const win = loadAppWindow();
  assert.equal(win.esc(null), '');
  assert.equal(win.esc(undefined), '');
});

test('formatValue() показывает булевы значения по-русски', () => {
  const win = loadAppWindow();
  assert.equal(win.formatValue(true), 'Да');
  assert.equal(win.formatValue(false), 'Нет');
});

test('formatValue() возвращает пустую строку для null/undefined, а не "null"/"undefined"', () => {
  const win = loadAppWindow();
  assert.equal(win.formatValue(null), '');
  assert.equal(win.formatValue(undefined), '');
});

test('formatValue() передаёт строки и числа как есть', () => {
  const win = loadAppWindow();
  assert.equal(win.formatValue('текст'), 'текст');
  assert.equal(win.formatValue(42), 42);
});

test('parseApiError()/errorMessage(): строковый detail показывается как есть, без сырого JSON', () => {
  const win = loadAppWindow();
  const err = new Error(JSON.stringify({ detail: 'Такая запись уже существует' }));
  assert.equal(win.errorMessage(err), 'Такая запись уже существует');
});

test('parseApiError(): объектный detail с code/message различим для диалогов подтверждения', () => {
  const win = loadAppWindow();
  const err = new Error(JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Дубликат' } }));
  const parsed = win.parseApiError(err);
  assert.equal(parsed.code, 'DUPLICATE_SYSTEM_NAME');
  assert.equal(parsed.message, 'Дубликат');
});

test('errorMessage(): не-JSON тело ответа (например HTML страница ошибки) не роняет разбор', () => {
  const win = loadAppWindow();
  const err = new Error('<html>500 Internal Server Error</html>');
  assert.doesNotThrow(() => win.errorMessage(err));
});

test('interfaceTemplateValue(): подставляет номер порта в шаблон имени интерфейса', () => {
  const win = loadAppWindow();
  assert.equal(win.interfaceTemplateValue('eth{n}', 3), 'eth3');
  assert.equal(win.interfaceTemplateValue('Gi0/{n0}', 3), 'Gi0/03');
});

test('optionHtml(): помечает selected у текущего значения, экранирует значения', () => {
  const win = loadAppWindow();
  const html = win.optionHtml([{ id: 'a', name: '<b>A</b>' }, { id: 'b', name: 'B' }], 'b');
  assert.match(html, /value="b" selected/);
  assert.match(html, /&lt;b&gt;A&lt;\/b&gt;/);
});

test('csvParse(): разбирает CSV построчно в массив массивов (заголовок — первая строка, как в openCsvImport)', () => {
  const win = loadAppWindow();
  const rows = win.csvParse('name,serial\nSW-1,ABC123\nSW-2,DEF456');
  assert.deepEqual(plain(rows), [
    ['name', 'serial'],
    ['SW-1', 'ABC123'],
    ['SW-2', 'DEF456'],
  ]);
});

test('csvParse(): поддерживает значения в кавычках с запятой внутри', () => {
  const win = loadAppWindow();
  const rows = win.csvParse('name,description\nSW-1,"Коммутатор, серверная A"');
  assert.deepEqual(plain(rows[1]), ['SW-1', 'Коммутатор, серверная A']);
});

test('notify(): создаёт toast с текстом сообщения и классом типа', () => {
  const win = loadAppWindow();
  win.notify('Операция выполнена', 'success');
  const toast = win.document.querySelector('#toast-container .toast');
  assert.ok(toast, 'toast должен появиться в #toast-container');
  assert.ok(toast.classList.contains('success'));
  assert.match(toast.textContent, /Операция выполнена/);
});

test('notify(): кнопка закрытия удаляет toast из DOM', () => {
  const win = loadAppWindow();
  win.notify('Ошибка сохранения', 'error');
  const closeBtn = win.document.querySelector('#toast-container .toast .toast-close');
  assert.ok(closeBtn);
  closeBtn.click();
  assert.equal(win.document.querySelectorAll('#toast-container .toast').length, 0);
});

test('notifyError(): извлекает сообщение из ошибки API и помечает toast как error', () => {
  const win = loadAppWindow();
  const err = new Error(JSON.stringify({ detail: 'Ресурс не найден' }));
  win.notifyError(err);
  const toast = win.document.querySelector('#toast-container .toast');
  assert.ok(toast.classList.contains('error'));
  assert.match(toast.textContent, /Ресурс не найден/);
});

test('showDashboard() при загрузке рендерит контент без явного вызова (см. bootstrap внизу app.js)', async () => {
  const win = loadAppWindow();
  // showDashboard() запускается асинхронно самим фактом загрузки файла — дождёмся её завершения.
  await new Promise((resolve) => setTimeout(resolve, 20));
  const html = win.document.getElementById('content').innerHTML;
  assert.match(html, /Dashboard/);
});
