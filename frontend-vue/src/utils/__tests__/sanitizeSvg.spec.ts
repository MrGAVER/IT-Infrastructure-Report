import { afterEach, describe, expect, it, vi } from 'vitest'
import { sanitizeSvg, sanitizeSvgIsolated } from '../sanitizeSvg'

describe('sanitizeSvg', () => {
  it('пустое значение', () => {
    expect(sanitizeSvg(null)).toBe('')
    expect(sanitizeSvg(undefined)).toBe('')
    expect(sanitizeSvg('')).toBe('')
  })

  it('пропускает обычную SVG-разметку без изменений по сути', () => {
    const result = sanitizeSvg('<svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#4f7cff"/></svg>')
    expect(result).toContain('<rect')
    expect(result).toContain('fill="#4f7cff"')
  })

  it('вырезает <script> внутри svg', () => {
    const result = sanitizeSvg('<svg><script>alert(1)</script><circle r="4"/></svg>')
    expect(result).not.toContain('<script')
    expect(result).not.toContain('alert')
    expect(result).toContain('<circle')
  })

  it('вырезает обработчики событий (on*)', () => {
    const result = sanitizeSvg('<svg onload="alert(1)"><rect onclick="alert(2)" width="1" height="1"/></svg>')
    expect(result).not.toContain('onload')
    expect(result).not.toContain('onclick')
  })

  it('вырезает <foreignObject>', () => {
    const result = sanitizeSvg('<svg><foreignObject><body onload="alert(1)">html внутри</body></foreignObject></svg>')
    expect(result.toLowerCase()).not.toContain('foreignobject')
  })

  it('вырезает javascript: в атрибутах-ссылках', () => {
    const result = sanitizeSvg('<svg><a href="javascript:alert(1)">клик</a></svg>')
    expect(result).not.toContain('javascript:')
  })
})

// B-07: клиентский белый список приведён к серверному (backend/app/services/diagram_icons.py:validate_svg_markup).
// Восемь проб из тикета — то, что раньше проходило или (последние пять) уже вырезалось: результат не должен
// содержать style, image, внешних href, url(http…), javascript:, data: и исполняемых атрибутов.
const PROBES: Array<[string, string]> = [
  ['<style> с глобальным CSS', '<svg><style>body{display:none!important}</style><rect width="1" height="1"/></svg>'],
  ['<image> с внешним адресом', '<svg><image href="https://evil.example/x.png"/></svg>'],
  ['style="fill:url(https://…)"', '<svg><rect style="fill:url(https://evil.example/t.svg#a)" width="1" height="1"/></svg>'],
  ['<a href="javascript:…">', '<svg><a href="javascript:alert(1)"><rect width="1" height="1"/></a></svg>'],
  ['onbegin на анимации', '<svg><rect width="1" height="1"><animate onbegin="alert(1)" attributeName="x"/></rect></svg>'],
  ['<set to="javascript:…">', '<svg><set attributeName="href" to="javascript:alert(1)"/></svg>'],
  ['<foreignObject> с HTML', '<svg><foreignObject><body onload="alert(1)">x</body></foreignObject></svg>'],
  ['<use href="data:…">', '<svg><use href="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="/></svg>'],
]

/** Приводит разметку к каноническому виду (XML-сериализация) — чтобы сравнивать «то же самое», а не байты:
 * DOMPurify отдаёт <path></path>, а в исходнике бывает <path/>. */
function canon(markup: string): string {
  const doc = new DOMParser().parseFromString(markup, 'image/svg+xml')
  return new XMLSerializer().serializeToString(doc.documentElement)
}

describe('sanitizeSvg — белый список как на сервере (B-07)', () => {
  it.each(PROBES)('%s: опасное вырезано', (_name, markup) => {
    const result = sanitizeSvg(markup)

    expect(result).not.toMatch(/<style/i)
    expect(result).not.toMatch(/<image/i)
    expect(result).not.toMatch(/\bstyle\s*=/i)
    expect(result).not.toMatch(/href\s*=\s*["'](?!#)/i)
    expect(result).not.toMatch(/url\(\s*["']?\s*(?!#)/i)
    expect(result).not.toMatch(/javascript:|data:|evil\.example|\bon\w+\s*=/i)
    expect(result).not.toMatch(/foreignobject|<set|<animate|<script/i)
    expect(result).toMatch(/^<svg/) // корень не потерян
  })

  it('ссылки: href/xlink:href только на #id, остальное вырезается', () => {
    const result = sanitizeSvg(
      '<svg><defs><rect id="r" width="1" height="1"/></defs><use href="#r"/><use xlink:href="#r"/><use href="https://evil.example/a.svg#r"/><use xlink:href="//evil.example/a.svg#r"/><use href="a.svg#r"/></svg>',
    )

    expect(result.match(/href="#r"/g)).toHaveLength(2)
    expect(result).not.toContain('evil.example')
    expect(result).not.toContain('a.svg')
  })

  it('url(): допустим только на #id (градиенты, clip-path), внешний адрес вырезается вместе с атрибутом', () => {
    const result = sanitizeSvg(
      '<svg><rect fill="url(#g)" clip-path="url(#c)" width="9" height="9"/><rect fill="url(https://evil.example/t.svg#a)" stroke="url( \'http://evil.example/x\' )" width="9" height="9"/></svg>',
    )

    expect(result).toContain('fill="url(#g)"')
    expect(result).toContain('clip-path="url(#c)"')
    expect(result).not.toContain('evil.example')
  })

  it('теги вне серверного белого списка вырезаются (a, filter, pattern, marker, switch, video, animate…)', () => {
    const result = sanitizeSvg(
      '<svg><a href="#x"><rect/></a><filter id="f"><feGaussianBlur stdDeviation="2"/></filter><pattern id="p"/><marker id="m"/><switch><rect/></switch><video/><animate attributeName="x"/><rect id="keep" width="1" height="1"/></svg>',
    )

    for (const tag of ['<a', '<filter', '<fegaussianblur', '<pattern', '<marker', '<switch', '<video', '<animate']) {
      expect(result.toLowerCase()).not.toContain(tag)
    }
    expect(result).toContain('id="keep"')
  })

  it('валидный svg с viewBox, path, fill="none", stroke="currentColor" не изменяется', () => {
    const markup =
      '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'

    expect(canon(sanitizeSvg(markup))).toBe(canon(markup))
  })

  it('встроенный запасной значок диаграммы (GENERIC_GLYPH) в той же обёртке, что и в DiagramDeviceNode, не изменяется', () => {
    const generic = '<path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    const markup = `<svg viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">${generic}</g></svg>`

    expect(canon(sanitizeSvg(markup))).toBe(canon(markup))
  })

  it('глифы, которые отдаёт бэкенд (rect/circle/path, fill, stroke, stroke-linecap/linejoin), рисуются без потерь', () => {
    // фрагменты SHAPE_GLYPHS из backend/app/services/diagram_icons.py (сервер, коммутатор, firewall)
    const glyphs = [
      '<rect x="4" y="2" width="16" height="20" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M4 9h16M4 16h16" stroke="currentColor" stroke-width="1.4"/><circle cx="7.2" cy="5.5" r="1"/><path d="M11 5.5h6M11 12.5h6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
      '<rect x="2" y="6" width="20" height="9" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 10.5h4.5M9.5 8.8l1.7 1.7-1.7 1.7" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
      '<circle cx="12" cy="12" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 1.2 10.6 4h2.8zM12 22.8 10.6 20h2.8z"/>',
    ]
    for (const glyph of glyphs) {
      const markup = `<svg viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">${glyph}</g></svg>`
      expect(canon(sanitizeSvg(markup))).toBe(canon(markup))
    }
  })

  it('градиенты, clipPath, mask, symbol и use на #id (допустимы на сервере) сохраняются, включая регистр тегов', () => {
    const markup =
      '<svg viewBox="0 0 24 24"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>' +
      '<radialGradient id="rg"><stop offset="0" stop-color="#f00"/></radialGradient><clipPath id="c"><rect width="5" height="5"/></clipPath><mask id="m"><rect width="9" height="9" fill="#fff"/></mask><symbol id="s"><circle r="2"/></symbol></defs>' +
      '<rect fill="url(#g)" clip-path="url(#c)" mask="url(#m)" width="9" height="9"/><use href="#s"/></svg>'

    expect(canon(sanitizeSvg(markup))).toBe(canon(markup))
  })
})

// R2-03: id внутри встроенных иконок глобальны в документе — каждому экземпляру иконки нужен свой префикс.
// B-04: очистка и переименование — один проход (sanitizeSvgIsolated), а не «очистка → строка → разбор → строка».
describe('sanitizeSvgIsolated — очистка и изоляция id за один проход (R2-03, B-04)', () => {
  const gradientIcon = (color: string) =>
    `<svg viewBox="0 0 24 24"><defs><linearGradient id="g"><stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="#000"/></linearGradient></defs><rect width="24" height="24" fill="url(#g)"/></svg>`

  /** Разбирает разметку так же, как это сделает v-html (HTML-парсер) — чтобы проверять итоговое дерево, а не строку. */
  function parse(markup: string): HTMLElement {
    const host = document.createElement('div')
    host.innerHTML = markup
    return host
  }

  it('пустое значение: пустая строка', () => {
    expect(sanitizeSvgIsolated('', 'ic1')).toBe('')
    expect(sanitizeSvgIsolated(null, 'ic1')).toBe('')
    expect(sanitizeSvgIsolated(undefined, 'ic1')).toBe('')
  })

  it('иконка без id: результат совпадает с тем, что отдаёт sanitizeSvg', () => {
    const markup = '<svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#4f7cff"/></svg>'

    expect(sanitizeSvgIsolated(markup, 'ic1')).toBe(sanitizeSvg(markup))
  })

  it('id получает префикс, url(#id) в fill следует за переименованием', () => {
    const result = sanitizeSvgIsolated(gradientIcon('#f00'), 'ic1')
    const doc = parse(result)

    expect(doc.querySelector('linearGradient')?.getAttribute('id')).toBe('ic1-g')
    expect(doc.querySelector('rect')?.getAttribute('fill')).toBe('url(#ic1-g)')
    expect(result).not.toMatch(/id="g"/)
    expect(result).not.toContain('url(#g)')
  })

  it('ссылка раньше определения (fill="url(#g)" стоит в документе до <linearGradient id="g">) тоже переписывается', () => {
    const result = sanitizeSvgIsolated('<svg><rect fill="url(#g)" width="1" height="1"/><defs><linearGradient id="g"/></defs></svg>', 'p')
    const doc = parse(result)

    expect(doc.querySelector('rect')?.getAttribute('fill')).toBe('url(#p-g)')
    expect(doc.querySelector('linearGradient')?.getAttribute('id')).toBe('p-g')
  })

  it('две иконки с одним id="g" и разными цветами на одной странице: все id уникальны, ссылки ведут на свою иконку', () => {
    const first = sanitizeSvgIsolated(gradientIcon('#f00'), 'ic1')
    const second = sanitizeSvgIsolated(gradientIcon('#00f'), 'ic2')
    const page = parse(first + second)

    const ids = Array.from(page.querySelectorAll('[id]')).map((el) => el.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const svg of Array.from(page.querySelectorAll('svg'))) {
      const target = svg
        .querySelector('rect')!
        .getAttribute('fill')!
        .match(/url\(#([^)]+)\)/)![1]
      expect(svg.querySelector(`[id="${target}"]`)).not.toBeNull() // ссылка указывает внутрь той же иконки
    }
    const colors = Array.from(page.querySelectorAll('stop[offset="0"]')).map((el) => el.getAttribute('stop-color'))
    expect(colors).toEqual(['#f00', '#00f'])
  })

  it('<use href="#a"> и xlink:href внутри той же иконки следуют за переименованием (в том числе без xmlns:xlink)', () => {
    const result = sanitizeSvgIsolated('<svg><defs><symbol id="a"><circle r="2"/></symbol></defs><use href="#a"/><use xlink:href="#a"/></svg>', 'ic1')

    expect(result.match(/href="#ic1-a"/g)).toHaveLength(2)
    expect(result).toContain('id="ic1-a"')
    expect(result).not.toMatch(/href="#a"/)
  })

  it('url(#id) переписывается в любых атрибутах (mask, clip-path, stroke) и во всех формах записи', () => {
    const result = sanitizeSvgIsolated(
      '<svg><defs><clipPath id="c"><rect/></clipPath><mask id="m"><rect/></mask><linearGradient id="g"/></defs>' +
        '<rect clip-path="url(#c)" mask="url( #m )" stroke="url(\'#g\')" fill="url(&quot;#g&quot;)"/></svg>',
      'p',
    )
    const rect = parse(result).querySelector('rect[clip-path]')!

    expect(rect.getAttribute('clip-path')).toBe('url(#p-c)')
    expect(rect.getAttribute('mask')).toBe('url( #p-m )')
    expect(rect.getAttribute('stroke')).toBe("url('#p-g')")
    expect(rect.getAttribute('fill')).toBe('url("#p-g")')
  })

  it('aria-labelledby/aria-describedby: список id переписывается целиком', () => {
    const result = sanitizeSvgIsolated('<svg aria-labelledby="t d" aria-describedby="d"><title id="t">Имя</title><desc id="d">Описание</desc></svg>', 'p')
    const svg = parse(result).querySelector('svg')!

    expect(svg.getAttribute('aria-labelledby')).toBe('p-t p-d')
    expect(svg.getAttribute('aria-describedby')).toBe('p-d')
  })

  it('ссылки на несуществующие id (в том числе внешние) не трогаются', () => {
    const result = sanitizeSvgIsolated('<svg><defs><linearGradient id="g"/></defs><rect fill="url(#g)" stroke="url(#other)"/><use href="#other"/></svg>', 'p')
    const doc = parse(result)

    expect(doc.querySelector('rect')?.getAttribute('stroke')).toBe('url(#other)')
    expect(doc.querySelector('use')?.getAttribute('href')).toBe('#other')
    expect(doc.querySelector('rect')?.getAttribute('fill')).toBe('url(#p-g)')
  })

  it('префикс очищается от символов, недопустимых в id', () => {
    const result = sanitizeSvgIsolated('<svg><rect id="a"/><rect id="b"/></svg>', 'v:0 x')

    expect(parse(result).querySelector('rect')?.getAttribute('id')).toBe('v_0_x-a')
    expect(result).toContain('id="v_0_x-b"')
  })

  it('id, совпадающие со свойствами document (DOM clobbering), DOMPurify убирает ещё до переименования', () => {
    const result = sanitizeSvgIsolated('<svg><rect id="cookie"/><rect id="body"/><rect id="ok"/></svg>', 'p')

    expect(result).not.toContain('cookie')
    expect(result).not.toMatch(/id="p-body"/)
    expect(result).toContain('id="p-ok"')
  })

  it('без префикса вывод совпадает с очищенным: изоляция ничего не добавляет, кроме самого префикса', () => {
    const result = sanitizeSvgIsolated(gradientIcon('#f00'), 'ic1')

    expect(result.replaceAll('ic1-', '')).toBe(sanitizeSvg(gradientIcon('#f00')))
  })

  it('«data-id=» вместо id: разметка не меняется', () => {
    const markup = '<svg><rect data-id="x"></rect></svg>'

    expect(sanitizeSvgIsolated(markup, 'p')).toBe(sanitizeSvg(markup))
  })

  it('правила очистки те же, что у sanitizeSvg: опасное вырезается и в режиме с изоляцией', () => {
    for (const [, markup] of PROBES) {
      const result = sanitizeSvgIsolated(markup, 'p')

      expect(result).not.toMatch(/<style|<image|<script|foreignobject|javascript:|data:|evil\.example|\bon\w+\s*=|\bstyle\s*=/i)
      expect(result).toMatch(/^<svg/)
    }
  })
})

// B-04: после очистки разметка превращается в строку ровно один раз. Повторный «разбор → сериализация» (прежний namespaceSvgIds)
// — классический вектор mXSS, поэтому лишних разборов в конвейере быть не должно.
describe('sanitizeSvgIsolated — один проход и устойчивость к mXSS (B-04)', () => {
  const SVG_NS = 'http://www.w3.org/2000/svg'

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('разметка разбирается ровно один раз (внутри DOMPurify): повторного DOMParser после очистки нет', () => {
    const parse = vi.spyOn(DOMParser.prototype, 'parseFromString')

    sanitizeSvgIsolated('<svg><defs><linearGradient id="g"/></defs><rect fill="url(#g)"/><use href="#g"/></svg>', 'ic1')

    expect(parse).toHaveBeenCalledTimes(1)
  })

  it('идемпотентность: повторная очистка результата ничего не меняет (строка стабильна)', () => {
    const inputs = [
      '<svg viewBox="0 0 24 24"><defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/></linearGradient></defs><rect fill="url(#g)" width="9" height="9"/></svg>',
      '<svg><defs><symbol id="a"><circle r="2"/></symbol></defs><use href="#a"/><use xlink:href="#a"/></svg>',
      '<svg aria-labelledby="t d"><title id="t">Имя</title><desc id="d">Описание &amp; детали</desc></svg>',
      '<svg><text id="x">a &lt; b &amp;&amp; c</text></svg>',
    ]
    for (const markup of inputs) {
      const once = sanitizeSvgIsolated(markup, 'ic1')

      expect(sanitizeSvg(once)).toBe(once)
    }
  })

  // Известные векторы mXSS (различия HTML- и SVG/MathML-разбора при повторной сериализации) плюс разметка с id, чтобы переименование
  // выполнялось на «подозрительном» дереве. Результат не должен ни содержать исполняемого, ни меняться при повторном разборе.
  const MXSS_VECTORS: Array<[string, string]> = [
    ['<style> внутри значения атрибута', '<svg></p><style><a id="</style><img src=1 onerror=alert(1)>">'],
    ['MathML + mglyph + style с комментарием', '<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;img src=1 onerror=alert(1)&gt;">'],
    ['CDATA в <desc>', '<svg><desc id="d"><![CDATA[</desc><script>alert(1)</script>]]></desc></svg>'],
    ['<style> внутри <title>', '<svg><title id="t"><style><img src=x onerror=alert(1)></style></title></svg>'],
    ['<foreignObject> с HTML внутри <a>', '<svg><a><foreignObject><p><img src=x onerror=alert(1)></p></foreignObject></a></svg>'],
    ['вложенные <form> и MathML (обход DOMPurify 2.0.0)', '<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>'],
    ['<style> в <tspan> с id', '<svg><text id="a"><tspan id="b"><style><img src=x onerror=alert(1)></style></tspan></text></svg>'],
    [
      '<noscript> с закрывающим тегом в атрибуте',
      '<svg><g id="x" aria-labelledby="x"><noscript><p title="</noscript><img src=x onerror=alert(1)>"></noscript></g></svg>',
    ],
    ['<textarea> в <desc>', '<svg><desc id="d"><textarea><img src=x onerror=alert(1)></textarea></desc></svg>'],
    ['разметка внутри значения id', '<svg><rect id=\'"><img src=x onerror=alert(1)>\' width="1" height="1"/></svg>'],
    ['обработчик на <use> внутри symbol с id', '<svg id="s"><symbol id="y"><use href="#y" onclick="alert(1)"/></symbol></svg>'],
  ]

  it.each(MXSS_VECTORS)('%s: ничего исполняемого, и повторный разбор даёт то же самое', (_name, vector) => {
    const result = sanitizeSvgIsolated(vector, 'ic1')

    // то, что получит v-html: разбираем строку HTML-парсером браузера
    const host = document.createElement('div')
    host.innerHTML = result

    // Проверяется дерево, а не строка: опасный текст может остаться в результате инертным — экранированным текстом
    // (`&lt;img … onerror=…&gt;` в <desc>) или значением атрибута в кавычках, и это безопасно. Значим только состав элементов.
    const elements = Array.from(host.querySelectorAll('*'))
    const foreign = elements.filter((el) => el.namespaceURI !== SVG_NS).map((el) => el.tagName)
    expect(foreign).toEqual([]) // ни одного HTML/MathML-элемента (img, script, style, form, textarea…) — только SVG
    expect(elements.map((el) => el.tagName.toLowerCase())).not.toContain('foreignobject')
    const withHandlers = elements.filter((el) => Array.from(el.attributes).some((a) => /^on/i.test(a.name)))
    expect(withHandlers).toEqual([])
    // устойчивость: строка → дерево → строка не меняет результат (иначе разбор в другом контексте мог бы дать другое дерево)
    expect(host.innerHTML).toBe(result)
  })
})
