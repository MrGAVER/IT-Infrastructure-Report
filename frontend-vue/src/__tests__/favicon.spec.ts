import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// /favicon.ico: бэкенд (api/frontend_assets.py) отдаёт файл из каталога сборки, а Vite кладёт туда всё содержимое public/.
// Без public/favicon.ico маршрут отвечал 404 и вкладка оставалась без иконки. Бэкенд-тесты подменяют каталог фронтенда
// временным, поэтому пропажу самого файла ловит только этот тест.
const FAVICON_PATH = path.resolve(process.cwd(), 'public/favicon.ico')
const INDEX_HTML_PATH = path.resolve(process.cwd(), 'index.html')

describe('favicon.ico', () => {
  const bytes = readFileSync(FAVICON_PATH)

  it('является настоящим ICO-файлом: заголовок «reserved=0, type=1» и хотя бы одно изображение', () => {
    expect(bytes.readUInt16LE(0)).toBe(0)
    expect(bytes.readUInt16LE(2)).toBe(1)
    expect(bytes.readUInt16LE(4)).toBeGreaterThanOrEqual(1)
  })

  it('содержит размеры 16, 32 и 48 пикселей — для вкладки, панели закладок и высокой плотности', () => {
    const count = bytes.readUInt16LE(4)
    // Запись каталога — 16 байт, ширина и высота в первых двух (0 означает 256).
    const sizes = Array.from({ length: count }, (_, i) => bytes[6 + i * 16] || 256).sort((a, b) => a - b)
    expect(sizes).toEqual(expect.arrayContaining([16, 32, 48]))
  })

  it('каждая запись каталога указывает внутрь файла (не обрезан)', () => {
    const count = bytes.readUInt16LE(4)
    for (let i = 0; i < count; i++) {
      const size = bytes.readUInt32LE(6 + i * 16 + 8)
      const offset = bytes.readUInt32LE(6 + i * 16 + 12)
      expect(offset + size).toBeLessThanOrEqual(bytes.length)
    }
  })

  it('подключён в index.html', () => {
    const html = readFileSync(INDEX_HTML_PATH, 'utf-8')
    expect(html).toMatch(/<link\s+rel="icon"\s+href="\/favicon\.ico"/)
  })
})
