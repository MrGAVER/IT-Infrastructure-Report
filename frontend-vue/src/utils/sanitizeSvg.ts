import DOMPurify from 'dompurify'

/** Теги, которые разрешает сервер (регистр — как в SVG: linearGradient, clipPath и т.д.). */
const ALLOWED_TAGS = [
  'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
  'defs', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'symbol', 'use',
  'text', 'tspan', 'title', 'desc',
]

/** url(...) в значении атрибута: захватывает адрес, чтобы проверить, что он указывает на #id (как _CSS_URL на сервере). */
const CSS_URL = /url\s*\(\s*(['"]?)\s*([^)'"]*)/gi

// Отдельный экземпляр DOMPurify: хук ниже не должен влиять на другие вызовы библиотеки в приложении.
const purify = DOMPurify(window)

purify.addHook('uponSanitizeAttribute', (_node, data) => {
  const name = data.attrName.toLowerCase()
  const value = data.attrValue.trim()
  // Ссылки — только на элемент внутри самого документа: https://…, data:, javascript: и относительные адреса не нужны.
  if (name === 'href' || name === 'xlink:href') {
    if (!value.startsWith('#')) data.keepAttr = false
    return
  }
  // fill="url(#grad)" допустим, fill="url(https://evil.example/t.svg#a)" — нет (CSP — второй слой, но не единственный).
  for (const match of value.matchAll(CSS_URL)) {
    if (!match[2].trim().startsWith('#')) {
      data.keepAttr = false
      return
    }
  }
})

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
 * Белый список — тот же, что на сервере (backend/app/services/diagram_icons.py:_ALLOWED_SVG_TAGS), а не
 * общий svg-профиль DOMPurify: профиль пропускает <style> (глобальный CSS на весь документ), <image>
 * (внешняя картинка), <a>, <filter>, анимации и атрибут style с url(), которые сервер отвергает. Правила
 * для атрибутов тоже серверные: href/xlink:href — только на #id внутри документа, url(...) — только на
 * #id, атрибут style не нужен (цвет задаётся fill/stroke). Они проверяются хуком атрибутов, а НЕ
 * параметром ALLOWED_URI_REGEXP: DOMPurify применяет его ко всем значениям атрибутов, и вариант /^#/
 * вырезал бы width="24", viewBox, d, fill="none" и stroke="currentColor" — иконки перестали бы рисоваться.
 *
 * Пример вызова:
 *   sanitizeSvg('<svg onload="alert(1)"><rect width="10" height="10"/></svg>')
 *   // -> '<svg><rect width="10" height="10"></rect></svg>' (onload вырезан)
 */
export function sanitizeSvg(svgMarkup: string | null | undefined): string {
  if (!svgMarkup) return ''
  return purify.sanitize(svgMarkup, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    FORBID_TAGS: ['script', 'foreignObject', 'style', 'image'],
    FORBID_ATTR: ['style', 'onload', 'onerror', 'onclick', 'onmouseover'],
  })
}
