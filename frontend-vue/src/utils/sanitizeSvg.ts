import DOMPurify from 'dompurify'

/** Теги, которые разрешает сервер (регистр — как в SVG: linearGradient, clipPath и т.д.). */
const ALLOWED_TAGS = [
  'svg',
  'g',
  'path',
  'rect',
  'circle',
  'ellipse',
  'line',
  'polyline',
  'polygon',
  'defs',
  'linearGradient',
  'radialGradient',
  'stop',
  'clipPath',
  'mask',
  'symbol',
  'use',
  'text',
  'tspan',
  'title',
  'desc',
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

/** Ссылка на элемент вида `url(#id)` в значении атрибута (кавычки и пробелы внутри скобок допустимы). */
const URL_REF = /(url\(\s*['"]?\s*)#([^)'"\s]+)/gi
/** Атрибуты со списком id через пробел (подпись и описание элемента ссылаются на <title>/<desc> по id). */
const ID_LIST_ATTRS = new Set(['aria-labelledby', 'aria-describedby'])

/**
 * R2-03 (ревью merge/review-f06-stage2-f05-executors): делает `id` внутри встроенной SVG-иконки уникальными в документе.
 *
 * Иконки вставляются в страницу как разметка (v-html), а `id` в документе глобальны: если две разные иконки на одной диаграмме
 * объявляют `<linearGradient id="g">` с разными цветами, обе ссылки `url(#g)` разрешатся на ПЕРВЫЙ элемент с таким id, и вторая
 * иконка нарисуется чужим градиентом. Тот же id мог совпасть и с id элемента самого приложения. Здесь каждый id получает
 * префикс экземпляра (`prefix-id`), а все ссылки на него внутри иконки — `href`/`xlink:href="#id"`, `url(#id)` в любом атрибуте
 * (fill, stroke, mask, clip-path, filter, marker-*) и `aria-labelledby`/`aria-describedby` — переписываются следом.
 *
 * Вызывать ПОСЛЕ `sanitizeSvg` (сначала очистка, потом переименование); результат повторно через DOMPurify не пропускать:
 * префикс гарантирует, что имена не совпадут со свойствами `document` (DOM clobbering), а значения атрибутов остаются теми же,
 * что уже прошли очистку. Ссылки на несуществующие id (в том числе внешние) не трогаются. Иконка без id возвращается как есть.
 *
 * Разбор — HTML-парсером, а не XML: вывод DOMPurify — HTML-сериализация, и в XML-парсере `xlink:href` без объявленного
 * `xmlns:xlink` дал бы parsererror (иконка молча осталась бы без изоляции). Так же разметку потом разберёт и v-html.
 *
 * @param prefix — уникальный для экземпляра компонента (`useId()`); недопустимые для id символы заменяются на «_».
 *
 * @example
 *   const uid = useId()
 *   const svg = computed(() => namespaceSvgIds(sanitizeSvg(markup.value), `ic${uid}`))
 *   // '<svg><defs><linearGradient id="g"/></defs><rect fill="url(#g)"/></svg>'
 *   //   → '<svg><defs><linearGradient id="icv-0-g"></linearGradient></defs><rect fill="url(#icv-0-g)"></rect></svg>'
 */
export function namespaceSvgIds(svgMarkup: string, prefix: string): string {
  // Быстрый выход без разбора: у большинства иконок id нет (проверка с запасом — «data-id=» тоже подходит, ниже это отсеется).
  if (!svgMarkup || !/\bid\s*=/i.test(svgMarkup)) return svgMarkup
  const safePrefix = prefix.replace(/[^A-Za-z0-9_-]/g, '_')
  const root = new DOMParser().parseFromString(svgMarkup, 'text/html').body

  const renamed = new Map<string, string>()
  for (const el of Array.from(root.querySelectorAll('[id]'))) {
    const id = el.getAttribute('id') ?? ''
    if (!id) continue
    const next = `${safePrefix}-${id}`
    renamed.set(id, next)
    el.setAttribute('id', next)
  }
  if (!renamed.size) return svgMarkup

  const mapped = (id: string) => renamed.get(id) ?? id
  for (const el of Array.from(root.querySelectorAll('*'))) {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase()
      if (name === 'id') continue
      if (name === 'href' || name === 'xlink:href') {
        if (attr.value.startsWith('#')) attr.value = `#${mapped(attr.value.slice(1))}`
      } else if (ID_LIST_ATTRS.has(name)) {
        attr.value = attr.value.split(/\s+/).filter(Boolean).map(mapped).join(' ')
      } else if (attr.value.includes('(')) {
        attr.value = attr.value.replace(URL_REF, (_match, head: string, id: string) => `${head}#${mapped(id)}`)
      }
    }
  }
  return root.innerHTML
}
