import { describe, expect, it } from 'vitest'
import { isValidIPv4, isValidPrefixLength } from '../ipValidation'

describe('isValidIPv4', () => {
  it('пустая строка — валидна (забота required, не этой функции)', () => {
    expect(isValidIPv4('')).toBe(true)
    expect(isValidIPv4('   ')).toBe(true)
  })

  it('обычные корректные адреса', () => {
    expect(isValidIPv4('192.168.1.1')).toBe(true)
    expect(isValidIPv4('10.0.0.1')).toBe(true)
    expect(isValidIPv4('0.0.0.0')).toBe(true)
    expect(isValidIPv4('255.255.255.255')).toBe(true)
  })

  it('пробелы по краям не мешают', () => {
    expect(isValidIPv4('  10.0.0.1  ')).toBe(true)
  })

  it('фикс п.2.1.3/п.3: произвольный текст — невалиден', () => {
    expect(isValidIPv4('не ip адрес')).toBe(false)
    expect(isValidIPv4('abc')).toBe(false)
    expect(isValidIPv4('управление активами')).toBe(false)
  })

  it('неверное количество октетов', () => {
    expect(isValidIPv4('10.0.0')).toBe(false)
    expect(isValidIPv4('10.0.0.0.1')).toBe(false)
    expect(isValidIPv4('10')).toBe(false)
  })

  it('октет вне диапазона 0-255', () => {
    expect(isValidIPv4('256.0.0.1')).toBe(false)
    expect(isValidIPv4('10.0.0.999')).toBe(false)
  })

  it('ведущие нули в октете отклоняются (неоднозначность дес./восьмеричной записи)', () => {
    expect(isValidIPv4('192.168.01.1')).toBe(false)
    expect(isValidIPv4('010.0.0.1')).toBe(false)
  })

  it('одиночный "0" в октете — по-прежнему валиден (не путать с "01")', () => {
    expect(isValidIPv4('10.0.0.1')).toBe(true)
  })

  it('нечисловые символы внутри октета', () => {
    expect(isValidIPv4('10.0.0.1a')).toBe(false)
    expect(isValidIPv4('10.0.0.-1')).toBe(false)
  })

  it('CIDR-нотация в самом поле IP — невалидна (префикс вводится отдельным полем)', () => {
    expect(isValidIPv4('10.0.0.1/24')).toBe(false)
  })
})

describe('isValidPrefixLength', () => {
  it('пустое/отсутствующее значение — валидно', () => {
    expect(isValidPrefixLength('')).toBe(true)
    expect(isValidPrefixLength(null)).toBe(true)
    expect(isValidPrefixLength(undefined)).toBe(true)
  })

  it('корректные значения диапазона 0-32 (границы включительно)', () => {
    expect(isValidPrefixLength('0')).toBe(true)
    expect(isValidPrefixLength('24')).toBe(true)
    expect(isValidPrefixLength('32')).toBe(true)
    expect(isValidPrefixLength(24)).toBe(true) // число, не только строка — prefix_length перед отправкой на бэкенд приводится к Number
  })

  it('фикс п.3: значения вне диапазона IPv4 (0-32) отклоняются', () => {
    expect(isValidPrefixLength('33')).toBe(false)
    expect(isValidPrefixLength('128')).toBe(false) // валидно для IPv6, но проект — только IPv4
    expect(isValidPrefixLength('-1')).toBe(false)
  })

  it('произвольный текст отклоняется', () => {
    expect(isValidPrefixLength('abc')).toBe(false)
    expect(isValidPrefixLength('24.5')).toBe(false)
  })
})
