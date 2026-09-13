import DOMPurify from 'dompurify'

/** Санитизация пользовательского SVG перед вставкой через v-html (код-ревью п.3.1, критичная
 * уязвимость — Stored XSS). DiagramIcon.svg_markup — пользовательский ввод (каталог кастомных
 * иконок диаграммы топологии сети), который рендерится через v-html в DiagramDeviceNode.vue
 * (сама диаграмма) и DeviceIconPicker.vue (предпросмотр при выборе/загрузке иконки). SVG —
 * исполняемый формат: без очистки <script>, <foreignObject> (может содержать произвольный
 * HTML) и обработчики событий (onload/onerror и т.п.) выполнились бы в браузере любого, кто
 * открыл диаграмму, включая администратора — прямой путь к похищению токена сессии из
 * localStorage (api/client.ts).
 *
 * Бэкенд отдельно отклоняет такой svg_markup при сохранении (см.
 * backend/app/services/diagram_icons.py:validate_svg_markup) — эта функция ВТОРОЙ, независимый
 * рубеж защиты (defense in depth): на случай уже существующих в БД записей, сохранённых до
 * появления серверной проверки, и любого другого источника markup, который может обойти её
 * (прямой запрос к API, будущий импорт/интеграция).
 *
 * USE_PROFILES: { svg: true } — разрешён именно набор тегов/атрибутов SVG (path, circle, g,
 * defs и т.п.), а не общий HTML-профиль; FORBID_TAGS дополнительно перестраховывается на
 * script/foreignObject (DOMPurify обычно и сам их не пропускает в svg-профиле, но здесь это
 * явное, читаемое намерение, а не подразумеваемое поведение библиотеки).
 *
 * Пример вызова:
 *   sanitizeSvg('<svg onload="alert(1)"><rect width="10" height="10"/></svg>')
 *   // -> '<svg><rect width="10" height="10"></rect></svg>' (onload вырезан)
 */
export function sanitizeSvg(svgMarkup: string | null | undefined): string {
  if (!svgMarkup) return ''
  return DOMPurify.sanitize(svgMarkup, {
    USE_PROFILES: { svg: true, svgFilters: true },
    FORBID_TAGS: ['script', 'foreignObject'],
    FORBID_ATTR: ['onload', 'onerror', 'onclick', 'onmouseover'],
  })
}
