import { describe, expect, it } from 'vitest'
import { sanitizeSvg } from '../sanitizeSvg'

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
    const markup = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'

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
