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

/** Единые правила очистки: и строковый режим (sanitizeSvg), и режим с изоляцией id (sanitizeSvgIsolated) обязаны пропускать одно и то же. */
const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [...ALLOWED_TAGS],
  FORBID_TAGS: ['script', 'foreignObject', 'style', 'image'],
  FORBID_ATTR: ['style', 'onload', 'onerror', 'onclick', 'onmouseover'],
}

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
  return purify.sanitize(svgMarkup, SANITIZE_CONFIG)
}

/** Ссылка на элемент вида `url(#id)` в значении атрибута (кавычки и пробелы внутри скобок допустимы). */
const URL_REF = /(url\(\s*['"]?\s*)#([^)'"\s]+)/gi
/** Атрибуты со списком id через пробел (подпись и описание элемента ссылаются на <title>/<desc> по id). */
const ID_LIST_ATTRS = new Set(['aria-labelledby', 'aria-describedby'])

/**
 * Дописывает `prefix-` ко всем `id` внутри уже очищенного дерева и переписывает ссылки на них: `href`/`xlink:href="#id"`,
 * `url(#id)` в любом атрибуте (fill, stroke, mask, clip-path, filter, marker-*) и `aria-labelledby`/`aria-describedby`.
 * Меняет дерево на месте.
 *
 * ИБ-03 (ревью merge/review-r3-executors): ссылки на id, которых внутри иконки нет (то есть на элементы страницы), СНИМАЮТ. Раньше они
 * оставались как есть, и `<use href="#чужой-id">` или `fill="url(#чужой-градиент)"` тянули в иконку элементы самого приложения или
 * соседней иконки — изоляция была неполной: переименовывались только свои id, а чужие оставались доступны по предсказуемому имени.
 * Снимается атрибут целиком (`href`, а не только значение; `fill="url(#нет)"` — весь `fill`, вместе с запасным цветом после url(): так
 * иконка не меняет вид в зависимости от того, что оказалось на странице). В `aria-labelledby`/`aria-describedby` убираются только
 * чужие id из списка, а если своих не осталось — весь атрибут.
 *
 * Два прохода по узлам нужны намеренно: ссылка может стоять в документе раньше, чем элемент, на который она ведёт
 * (`<rect fill="url(#g)">` до `<linearGradient id="g">`), поэтому сначала собираются все id, потом переписываются ссылки.
 * Второй проход выполняется и для иконки вовсе без id: ссылки на чужие id нужно снять и в ней.
 */
function prefixIdsInPlace(root: ParentNode, prefix: string): void {
  const renamed = new Map<string, string>()
  for (const el of Array.from(root.querySelectorAll('[id]'))) {
    const id = el.getAttribute('id') ?? ''
    if (!id) continue
    const next = `${prefix}-${id}`
    renamed.set(id, next)
    el.setAttribute('id', next)
  }

  for (const el of Array.from(root.querySelectorAll('*'))) {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase()
      if (name === 'id') continue
      if (name === 'href' || name === 'xlink:href') {
        if (!attr.value.startsWith('#')) continue
        const next = renamed.get(attr.value.slice(1))
        if (next === undefined) el.removeAttributeNode(attr)
        else attr.value = `#${next}`
      } else if (ID_LIST_ATTRS.has(name)) {
        const own = attr.value.split(/\s+/).flatMap((id) => {
          const next = renamed.get(id)
          return next === undefined ? [] : [next]
        })
        if (own.length) attr.value = own.join(' ')
        else el.removeAttributeNode(attr)
      } else if (attr.value.includes('(')) {
        let dangling = false
        const rewritten = attr.value.replace(URL_REF, (match, head: string, id: string) => {
          const next = renamed.get(id)
          if (next === undefined) {
            dangling = true
            return match
          }
          return `${head}#${next}`
        })
        if (dangling) el.removeAttributeNode(attr)
        else attr.value = rewritten
      }
    }
  }
}

/**
 * Очищает пользовательский SVG (те же правила, что у `sanitizeSvg`) и делает `id` внутри него уникальными в документе —
 * за ОДИН проход: разметка разбирается один раз (внутри DOMPurify), очищается, `id` и ссылки на них переименовываются прямо в
 * очищенном дереве, и только потом оно один раз сериализуется в строку.
 *
 * B-04 (ревью merge/review-r1-r2-executors): раньше это были две отдельные функции — `sanitizeSvg(...)` возвращала СТРОКУ, а
 * `namespaceSvgIds(...)` заново разбирала её через DOMParser и снова сериализовала через innerHTML. Каждый такой цикл «разбор →
 * сериализация» после очистки — классический вектор mXSS: разные контексты разбирают одну и ту же строку по-разному, и то, что
 * DOMPurify проверил как безобидное дерево, может превратиться в другое при повторном разборе. Теперь после очистки в строку
 * дерево превращается ровно один раз — так же, как это делает сам DOMPurify, — а до этого мы меняем только значения `id` и ссылок
 * на них (дописываем префикс), ничего нового в разметку не вносим.
 *
 * Зачем изоляция id: иконки вставляются в страницу как разметка (v-html), а `id` в документе глобальны. Если две разные иконки на
 * одной диаграмме объявляют `<linearGradient id="g">` с разными цветами, обе ссылки `url(#g)` разрешатся на ПЕРВЫЙ элемент с таким
 * id, и вторая иконка нарисуется чужим градиентом; тот же id мог совпасть и с id элемента самого приложения (R2-03). Префикс также
 * не даёт id совпасть со свойствами `document` (DOM clobbering): DOMPurify и так убирает такие id, а префикс страхует остальное.
 *
 * Иконка без id и без ссылок на чужие id возвращается в том виде, в каком её отдала бы `sanitizeSvg`; ссылки на id вне иконки снимаются (ИБ-03).
 *
 * @param idPrefix — уникальный для экземпляра компонента (`useId()`); недопустимые для id символы заменяются на «_».
 *
 * @example
 *   const uid = useId()
 *   const svg = computed(() => sanitizeSvgIsolated(markup.value, `ic${uid}`))
 *   // '<svg><defs><linearGradient id="g"/></defs><rect fill="url(#g)"/></svg>'
 *   //   → '<svg><defs><linearGradient id="ic0-g"></linearGradient></defs><rect fill="url(#ic0-g)"></rect></svg>'
 */
export function sanitizeSvgIsolated(svgMarkup: string | null | undefined, idPrefix: string): string {
  if (!svgMarkup) return ''
  // RETURN_DOM: DOMPurify отдаёт очищенное дерево (body inert-документа), не превращая его в строку — переименование идёт по нему.
  const body = purify.sanitize(svgMarkup, { ...SANITIZE_CONFIG, RETURN_DOM: true })
  if (!(body instanceof Element)) return '' // DOMPurify вернул null: разметку не удалось разобрать
  prefixIdsInPlace(body, idPrefix.replace(/[^A-Za-z0-9_-]/g, '_'))
  return body.innerHTML
}
