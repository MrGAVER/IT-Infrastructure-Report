#!/usr/bin/env node
// Гейт `npm audit` для runtime-зависимостей — замена прямого `npm audit --omit=dev --audit-level=high` в CI.
//
// Зачем. У npm нет списка исключений: если для известной уязвимости ещё нет исправленной версии, шаг CI красный для всех и
// «лечить» его нечем (`npm audit fix --force` понижает vue-router, а `overrides` ставит ту же уязвимую версию). Этот скрипт
// делает то же, что прямой вызов, плюс ЯВНЫЕ ИСКЛЮЧЕНИЯ по идентификатору advisory: каждое — с причиной и сроком действия.
// После срока исключение перестаёт действовать, и гейт снова падает — решение придётся пересмотреть, а не забыть.
//
// Что остаётся строгим: любая другая уязвимость уровня high и выше падает; исключение действует только на advisory с указанным
// id; ошибка самого `npm audit` (нет сети, битый ответ) — тоже падение, а не «чисто».

import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

/** Порядок серьёзности advisory npm. */
export const SEVERITY_RANK = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 }

/**
 * Принятые исключения. Добавлять только когда исправленной версии нет (first_patched_version: null) И уязвимый код не попадает
 * в собранное приложение — проверяйте это и записывайте в reason. `expires` — последний день действия (включительно), YYYY-MM-DD.
 *
 * Сейчас список пуст. Исключение для picomatch (GHSA-fc5q-39xc-vjpf, ReDoS в picomatch <= 4.0.7), действовавшее с 2.160.0, снято:
 * advisory отозван (withdrawn) 2026-11-18, и `npm audit` его больше не показывает, хотя исправленной версии picomatch так и нет.
 */
export const ALLOWLIST = []

/** id advisory из его ссылки (`https://github.com/advisories/GHSA-…` → `GHSA-…`); без ссылки — числовой source npm. */
export function advisoryId(via) {
  const fromUrl = typeof via.url === 'string' ? via.url.split('/').filter(Boolean).pop() : undefined
  return fromUrl || String(via.source)
}

/**
 * Все advisory из отчёта `npm audit --json`. В `vulnerabilities[*].via` лежат либо объекты advisory, либо строки-имена пакетов
 * (производные уязвимости — те, что наследуются от зависимости); цепочка любой производной заканчивается объектом, поэтому
 * достаточно собрать объекты. Повторы (один advisory у нескольких пакетов) схлопываются по id.
 */
export function collectAdvisories(report) {
  const found = new Map()
  for (const vuln of Object.values(report.vulnerabilities ?? {})) {
    for (const via of vuln.via ?? []) {
      if (typeof via !== 'object' || via === null) continue
      found.set(advisoryId(via), { id: advisoryId(via), package: via.name, severity: via.severity, title: via.title, url: via.url })
    }
  }
  return [...found.values()]
}

/**
 * Разбор отчёта.
 * @returns {{ failing: object[], allowed: object[], expired: object[], unused: object[] }}
 *   failing — уязвимости уровня `level` и выше без действующего исключения (из-за них гейт падает);
 *   allowed — покрыты действующим исключением; expired — исключение есть, но срок вышел (входят и в failing);
 *   unused — исключения, для которых в отчёте уже нет advisory (их пора удалить).
 */
export function evaluateAudit(report, { allowlist = ALLOWLIST, level = 'high', now = new Date() } = {}) {
  const minRank = SEVERITY_RANK[level]
  if (minRank === undefined) throw new Error(`Неизвестный уровень серьёзности: ${level}`)
  const today = now.toISOString().slice(0, 10)
  const advisories = collectAdvisories(report)

  const failing = []
  const allowed = []
  const expired = []
  for (const advisory of advisories) {
    if ((SEVERITY_RANK[advisory.severity] ?? SEVERITY_RANK.critical) < minRank) continue
    const rule = allowlist.find((r) => r.id === advisory.id)
    if (!rule) failing.push(advisory)
    else if (today > rule.expires) {
      expired.push({ ...advisory, rule })
      failing.push({ ...advisory, rule })
    } else allowed.push({ ...advisory, rule })
  }
  const present = new Set(advisories.map((a) => a.id))
  const unused = allowlist.filter((r) => !present.has(r.id))
  return { failing, allowed, expired, unused }
}

/** Запуск `npm audit --omit=dev --json`; код возврата npm при найденных уязвимостях ненулевой — это не ошибка запуска. */
function runNpmAudit() {
  const result = spawnSync('npm', ['audit', '--omit=dev', '--json'], { encoding: 'utf8', shell: process.platform === 'win32' })
  if (result.error) throw result.error
  let report
  try {
    report = JSON.parse(result.stdout)
  } catch {
    throw new Error(`npm audit вернул не JSON (код ${result.status}): ${(result.stderr || result.stdout || '').slice(0, 400)}`)
  }
  if (report.error) throw new Error(`npm audit не выполнился: ${report.error.summary ?? report.error.code ?? 'неизвестная ошибка'}`)
  return report
}

function main() {
  let outcome
  try {
    outcome = evaluateAudit(runNpmAudit())
  } catch (err) {
    console.error(`audit-gate: ${err.message}`)
    process.exit(2)
  }
  for (const a of outcome.allowed) {
    console.log(`audit-gate: исключение до ${a.rule.expires} — ${a.id} (${a.package}, ${a.severity}): ${a.title}`)
  }
  for (const r of outcome.unused) {
    console.log(`audit-gate: исключение ${r.id} (${r.package}) больше не нужно — advisory в отчёте нет, удалите его из ALLOWLIST`)
  }
  if (outcome.failing.length) {
    for (const a of outcome.failing) {
      const why = a.rule ? ` — срок исключения вышел ${a.rule.expires}` : ''
      console.error(`audit-gate: ${a.severity} ${a.id} (${a.package}): ${a.title}${why}\n  ${a.url}`)
    }
    process.exit(1)
  }
  console.log(`audit-gate: уязвимостей уровня high и выше без исключений нет (исключений в действии: ${outcome.allowed.length})`)
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main()
