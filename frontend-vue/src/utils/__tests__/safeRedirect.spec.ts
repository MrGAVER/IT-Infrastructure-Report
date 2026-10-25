import { describe, it, expect } from 'vitest'
import { safeRedirect } from '../safeRedirect'

describe('safeRedirect', () => {
  it.each([
    '/devices?x=1',
    '/devices',
    '/devices/dev-1?tab=ports#row-3',
    '/report-templates/t-1/editor',
    '/loginfo', // начинается с «/login», но это другой путь
    '/dashboard',
  ])('внутренний путь %s проходит без изменений', (value) => {
    expect(safeRedirect(value)).toBe(value)
  })

  it.each<[string, unknown]>([
    ['адрес без схемы', '//evil.example'],
    ['адрес без схемы с путём', '//evil.example/path'],
    ['абсолютный адрес', 'https://evil.example'],
    ['схема javascript', 'javascript:alert(1)'],
    ['относительный путь', 'devices'],
    ['экран входа', '/login'],
    ['экран входа с query', '/login?redirect=/devices'],
    ['экран входа с хвостовым слэшем', '/login/'],
    ['экран входа в закодированном виде', '/%6cogin'],
    ['обратная косая черта (браузер сделает из неё //)', '/\\evil.example'],
    ['закодированная обратная косая черта', '/%5cevil.example'],
    ['закодированные слэши', '/%2f%2fevil.example'],
    ['табуляция внутри адреса', '/\t/evil.example'],
    ['перевод строки', '/dev\nices'],
    ['сегмент ..', '/devices/../login'],
    ['закодированный сегмент ..', '/%2e%2e/etc/passwd'],
    ['закодированный сегмент . в верхнем регистре', '/devices/%2E/x'],
    ['битая %-последовательность', '/devices/%E0%A4%A'],
    ['пустая строка', ''],
    ['не строка: число', 42],
    ['не строка: null', null],
    ['не строка: undefined', undefined],
    ['не строка: массив (повторяющийся параметр ?redirect=a&redirect=b)', ['/a', '/b']],
    ['не строка: объект', { path: '/devices' }],
  ])('%s → запасной адрес /dashboard', (_title, value) => {
    expect(safeRedirect(value)).toBe('/dashboard')
  })

  it('граница длины: 512 символов проходят, 513 — нет', () => {
    const ok = '/' + 'a'.repeat(511)
    const tooLong = '/' + 'a'.repeat(512)
    expect(ok).toHaveLength(512)
    expect(safeRedirect(ok)).toBe(ok)
    expect(safeRedirect(tooLong)).toBe('/dashboard')
  })

  it('запасной адрес можно переопределить', () => {
    expect(safeRedirect('//evil.example', '/')).toBe('/')
    expect(safeRedirect(undefined, '/devices')).toBe('/devices')
    expect(safeRedirect('/vlans', '/')).toBe('/vlans')
  })
})
