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
