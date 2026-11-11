// Страж предупреждений Vue для setup.ts: `[Vue warn]` в тесте — ошибка этого теста (B-07 ревью merge/review-r1-r2-executors).
//
// Прогон тестов сыпал около 1700 таких предупреждений (ссылки без роутера, неполные фикстуры, число вместо строки в пропсе). Это не
// косметика: в тысячах строк журнала утонули бы настоящие — например, неверный тип пропса в боевом компоненте. Порог «не больше N»
// размывается сам (всегда есть соблазн поднять N), поэтому планка здесь нулевая: предупреждение ломает тест, который его вызвал.
//
// Как ловим. Vue печатает предупреждения через console.warn с префиксом `[Vue warn]`; обёртка над console.warn складывает их в список,
// а setup.ts после каждого теста (уже после размонтирования его компонентов — размонтирование тоже может предупреждать) проверяет, что
// список пуст. Обёртка, а не app.config.warnHandler: handler действует только на приложения, созданные через mount() из VTU, а спеки с
// собственным createApp() остались бы вне контроля. Тест, который сам шпионит за console.warn (`vi.spyOn(console, 'warn')`), подменяет
// и эту обёртку, а после mockRestore() она возвращается на место.
//
// Тест, который предупреждение вызывает НАМЕРЕННО (проверяет, что компонент жалуется на неверный пропс), забирает его через
// takeVueWarnings() — тогда страж его не увидит.

const VUE_WARN_PREFIX = '[Vue warn]'

const collected: string[] = []

/** Подменяет console.warn: предупреждения Vue копятся для стража, всё остальное печатается как обычно. Вызывается один раз из setup.ts. */
export function installVueWarningCollector(): void {
  const original = console.warn.bind(console)
  console.warn = (...args: unknown[]) => {
    const [first] = args
    if (typeof first === 'string' && first.startsWith(VUE_WARN_PREFIX)) collected.push(args.map(String).join(' '))
    else original(...args)
  }
}

/** Забирает накопленные предупреждения Vue (и очищает список): для теста, которому они нужны, и для стража. */
export function takeVueWarnings(): string[] {
  return collected.splice(0)
}

/** Бросает ошибку, если в тесте были непринятые предупреждения Vue. Вызывается из setup.ts ПОСЛЕ размонтирования компонентов теста. */
export function assertNoVueWarnings(): void {
  const warnings = takeVueWarnings()
  if (warnings.length === 0) return
  const shown = warnings.slice(0, 3).map((w) => `  • ${w.split('\n').slice(0, 4).join('\n    ')}`)
  const rest = warnings.length > shown.length ? `\n  … и ещё ${warnings.length - shown.length}` : ''
  throw new Error(
    `Тест вызвал предупреждения Vue (${warnings.length}): исправьте причину (фикстура, пропсы, роутер) или, если предупреждение ожидаемо, заберите его ` +
      `через takeVueWarnings() из src/__tests__/vueWarnings.ts.\n${shown.join('\n')}${rest}`,
  )
}
