import { describe, it, expect } from 'vitest'
import { ALLOWLIST, advisoryId, collectAdvisories, evaluateAudit } from '../../scripts/audit-gate.mjs'
import type { AllowRule, AuditReport } from '../../scripts/audit-gate.mjs'

const PICOMATCH_URL = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf'

/** Форма отчёта `npm audit --json`: у пакета с advisory в via — объект, у производных (fdir, vite…) — имена пакетов. */
function report(vulns: AuditReport['vulnerabilities']): AuditReport {
  return { vulnerabilities: vulns }
}
const picomatchReport = report({
  picomatch: { via: [{ source: 1247710, name: 'picomatch', severity: 'high', title: 'ReDoS', url: PICOMATCH_URL }] },
  fdir: { via: ['picomatch'] },
  vite: { via: ['fdir', 'tinyglobby'] },
})

const rule = (overrides: Partial<AllowRule> = {}): AllowRule => ({
  id: 'GHSA-fc5q-39xc-vjpf',
  package: 'picomatch',
  reason: 'нет исправления',
  expires: '2026-12-31',
  ...overrides,
})
const on = (day: string) => new Date(`${day}T12:00:00Z`)

describe('audit-gate: разбор отчёта', () => {
  it('id берётся из ссылки advisory, без ссылки — из числового source', () => {
    expect(advisoryId({ url: PICOMATCH_URL, source: 1 })).toBe('GHSA-fc5q-39xc-vjpf')
    expect(advisoryId({ source: 1247710 })).toBe('1247710')
  })

  it('собирает advisory только из объектов via: производные пакеты (строки) не считаются, повторы схлопываются', () => {
    const doubled = report({
      picomatch: { via: [{ source: 1, name: 'picomatch', severity: 'high', title: 'ReDoS', url: PICOMATCH_URL }] },
      'other-copy': { via: [{ source: 1, name: 'picomatch', severity: 'high', title: 'ReDoS', url: PICOMATCH_URL }, 'fdir'] },
    })

    expect(collectAdvisories(doubled).map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
  })

  it('пустой отчёт (нет уязвимостей) разбирается без ошибок', () => {
    expect(collectAdvisories({})).toEqual([])
    expect(evaluateAudit({}, { allowlist: [rule()], now: on('2026-11-18') })).toMatchObject({ failing: [], allowed: [], unused: [rule()] })
  })
})

describe('audit-gate: исключения', () => {
  it('уязвимость high без исключения валит гейт', () => {
    const out = evaluateAudit(picomatchReport, { allowlist: [], now: on('2026-11-18') })

    expect(out.failing.map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
    expect(out.allowed).toEqual([])
  })

  it('действующее исключение пропускает именно этот advisory', () => {
    const out = evaluateAudit(picomatchReport, { allowlist: [rule()], now: on('2026-11-18') })

    expect(out.failing).toEqual([])
    expect(out.allowed.map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
  })

  it('в последний день срока исключение ещё действует, на следующий — нет', () => {
    expect(evaluateAudit(picomatchReport, { allowlist: [rule()], now: on('2026-12-31') }).failing).toEqual([])

    const after = evaluateAudit(picomatchReport, { allowlist: [rule()], now: on('2027-01-01') })
    expect(after.failing.map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
    expect(after.expired.map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
  })

  it('исключение на один advisory не прикрывает другой advisory того же пакета', () => {
    const second = report({
      picomatch: {
        via: [
          { source: 1, name: 'picomatch', severity: 'high', title: 'ReDoS', url: PICOMATCH_URL },
          { source: 2, name: 'picomatch', severity: 'critical', title: 'Новая уязвимость', url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc' },
        ],
      },
    })

    const out = evaluateAudit(second, { allowlist: [rule()], now: on('2026-11-18') })

    expect(out.failing.map((a) => a.id)).toEqual(['GHSA-aaaa-bbbb-cccc'])
    expect(out.allowed.map((a) => a.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
  })

  it('уровень ниже порога (moderate при пороге high) гейт не валит', () => {
    const moderate = report({
      pkg: { via: [{ source: 3, name: 'pkg', severity: 'moderate', title: 'Средняя', url: 'https://github.com/advisories/GHSA-1111-2222-3333' }] },
    })

    expect(evaluateAudit(moderate, { allowlist: [], now: on('2026-11-18') }).failing).toEqual([])
    expect(evaluateAudit(moderate, { allowlist: [], level: 'moderate', now: on('2026-11-18') }).failing).toHaveLength(1)
  })

  it('исключение, для которого advisory уже нет в отчёте, помечается как ненужное', () => {
    const out = evaluateAudit({}, { allowlist: [rule()], now: on('2026-11-18') })

    expect(out.unused.map((r) => r.id)).toEqual(['GHSA-fc5q-39xc-vjpf'])
  })

  it('неизвестный уровень серьёзности — ошибка, а не молчаливое «всё чисто»', () => {
    expect(() => evaluateAudit({}, { level: 'urgent' as never })).toThrow('Неизвестный уровень')
  })

  it('список исключений проекта: у каждого есть причина, срок в формате даты и id advisory', () => {
    for (const r of ALLOWLIST) {
      expect(r.id).toMatch(/^GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}$/)
      expect(r.expires).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(r.reason.length).toBeGreaterThan(40)
    }
  })

  it('исключение для picomatch снято: advisory GHSA-fc5q-39xc-vjpf отозван 2026-11-18, `npm audit` его больше не показывает', () => {
    expect(ALLOWLIST.map((r) => r.id)).not.toContain('GHSA-fc5q-39xc-vjpf')
  })
})
