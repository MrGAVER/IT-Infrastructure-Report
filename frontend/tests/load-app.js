'use strict';
/**
 * Загружает frontend/static/app.js в изолированный jsdom-контекст: window/document существуют,
 * но сетевых запросов не происходит (fetch подменяется заглушкой, если тесту не нужны реальные
 * данные — конкретный тест переопределяет window.fetch сам при необходимости).
 *
 * app.js написан как обычный (не-модульный) скрипт для браузера: top-level `function foo(){}`
 * становится свойством window. Здесь это воспроизводится через vm.runInContext с window как
 * глобальным объектом контекста — тот же механизм, что использует браузер для classic <script>.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { JSDOM } = require('jsdom');

const APP_JS_PATH = path.join(__dirname, '..', 'static', 'app.js');
const CORE_JS_PATH = path.join(__dirname, '..', 'static', 'core.js');
const VM_EDITORS_JS_PATH = path.join(__dirname, '..', 'static', 'vm-editors.js');
const REPORT_BUILDER_JS_PATH = path.join(__dirname, '..', 'static', 'report_builder.js');
const INDEX_HTML_PATH = path.join(__dirname, '..', 'index.html');

function loadAppWindow({ fetchImpl, withReportBuilder = false } = {}) {
  // Uses the real index.html as the DOM fixture (minus the <script> tags, loaded manually below)
  // rather than a hand-maintained stub: app.js reads several elements by their global `id` (e.g.
  // bare `content` for <div id="content">, via the browser's window-named-property-access
  // feature that jsdom also implements) — a stub HTML would silently drift from the real page.
  const html = fs.readFileSync(INDEX_HTML_PATH, 'utf-8').replace(/<script[^>]*><\/script>/g, '');
  const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: 'outside-only' });
  const { window } = dom;
  // app.js calls showDashboard() unconditionally as its last top-level statement (this is how
  // it bootstraps itself when loaded as a classic <script> in the real page), which calls
  // fetch(). A default stub resolves it harmlessly so any test can load the file; a test that
  // cares about network behavior can pass its own fetchImpl instead.
  window.fetch = fetchImpl || (() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve('{}'),
  }));
  const context = dom.getInternalVMContext();
  // core.js first — same order as <script> tags in index.html; app.js/report_builder.js
  // reference its functions/constants (esc, notify, get, api, ...) at call time, not at load
  // time, but keeping the real load order here avoids the test fixture silently diverging
  // from the actual page if that ever changes.
  vm.runInContext(fs.readFileSync(CORE_JS_PATH, 'utf-8'), context, { filename: CORE_JS_PATH });
  vm.runInContext(fs.readFileSync(VM_EDITORS_JS_PATH, 'utf-8'), context, { filename: VM_EDITORS_JS_PATH });
  vm.runInContext(fs.readFileSync(APP_JS_PATH, 'utf-8'), context, { filename: APP_JS_PATH });
  if (withReportBuilder) {
    vm.runInContext(fs.readFileSync(REPORT_BUILDER_JS_PATH, 'utf-8'), context, { filename: REPORT_BUILDER_JS_PATH });
  }
  return window;
}

module.exports = { loadAppWindow };
