// Состояние экрана «Проверка данных»: загрузка находок и каталога правил, фильтры и страницы.
// Находки читаются одним запросом (api/consistency.ts), фильтрация и разбиение на страницы — на клиенте.
import { computed, reactive, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import { APPROVAL_BATCH_LIMIT, approveFinding, approveFindings, fetchConsistency, fetchConsistencyRules, revokeApproval } from '../api/consistency'
import type { ConsistencyFinding, ConsistencyReport, ConsistencyRule } from '../api/consistency'
import { DEFAULT_FILTERS, countActive, filterFindings, hasActiveFilters, sheetsWithFindings } from '../utils/consistencyFilter'
import type { ConsistencyFilters } from '../utils/consistencyFilter'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, pageAfterSizeChange } from '../utils/pageSize'
import { pluralRu } from '../utils/plural'
import { useToast } from './useToast'

/** Значение `busy` на время пакетного одобрения: настоящему отпечатку (64 hex) оно не равно. */
const BATCH_BUSY = 'batch'

export function useConsistencyReport() {
  const { notify, notifyError } = useToast()
  const report = ref<ConsistencyReport | null>(null)
  const rules = ref<ConsistencyRule[]>([])
  const loading = ref(false)
  const errorText = ref('')
  const filters = reactive<ConsistencyFilters>({ ...DEFAULT_FILTERS })
  const page = ref(1)
  // Размер страницы здесь не запоминается: список настроек запоминаемых списков задаёт сервер (preferences), а этот экран — справочный.
  const pageSize = ref(DEFAULT_PAGE_SIZE)

  /** Отпечаток находки, по которой сейчас идёт запрос на одобрение или отзыв: пока он не завершён, остальные кнопки заблокированы. */
  const busy = ref<string | null>(null)

  // Ответ более раннего запроса не должен затереть более поздний («Обновить» дважды подряд).
  let requestSeq = 0

  async function load(): Promise<void> {
    const seq = ++requestSeq
    loading.value = true
    errorText.value = ''
    try {
      // Каталог правил нужен только для названий и выбора правила: без него находки всё равно читаемы (название = код правила).
      const [loaded, catalog] = await Promise.all([fetchConsistency(), fetchConsistencyRules().catch(() => [] as ConsistencyRule[])])
      if (seq !== requestSeq) return
      report.value = loaded
      rules.value = catalog
    } catch (err) {
      if (seq !== requestSeq) return
      // Проверка, которая молча не сработала, хуже отсутствующей: показываем причину и даём повторить.
      errorText.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  const findings = computed(() => report.value?.findings ?? [])
  const filtered = computed(() => filterFindings(findings.value, filters))
  const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
  const pageItems = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
  const filtersActive = computed(() => hasActiveFilters(filters))
  const sheets = computed(() => sheetsWithFindings(findings.value))
  /** Счётчики экрана: «требуют внимания» по важности и число одобренных. */
  const counts = computed(() => countActive(findings.value))

  const titles = computed(() => new Map(rules.value.map((rule) => [rule.code, rule.title])))
  /** Названия правил, по которым есть находки (для выбора «Правило»); код правила — запасное название. */
  const ruleOptions = computed(() =>
    [...new Set(findings.value.map((item) => item.rule))]
      .map((code) => ({ code, title: titles.value.get(code) ?? code }))
      .sort((a, b) => a.title.localeCompare(b.title, 'ru')),
  )
  const ruleTitle = (code: string) => titles.value.get(code) ?? code

  // Любое изменение фильтров возвращает на первую страницу: иначе после сужения выборки можно оказаться за её последней страницей.
  watch(filters, () => (page.value = 1))

  // Одобрение убирает строку из списка «требуют внимания»: если это была последняя строка последней страницы, страница исчезает.
  watch(pageCount, (count) => {
    if (page.value > count) page.value = count
  })

  function patchFinding(fingerprint: string, patch: Partial<ConsistencyFinding>): void {
    if (!report.value) return
    report.value = { ...report.value, findings: report.value.findings.map((item) => (item.fingerprint === fingerprint ? { ...item, ...patch } : item)) }
  }

  /** Состояние могло измениться, пока экран был открыт (проблему исправили, одобрение отозвали): тогда перечитываем проверку. */
  async function handleStale(err: unknown, message: string): Promise<void> {
    if (err instanceof ApiError && err.status === 404) {
      notify(message, 'error')
      await load()
    } else {
      notifyError(err)
    }
  }

  /** Одобряет проблему; true — одобрено (окно комментария можно закрывать). */
  async function approve(finding: ConsistencyFinding, comment: string | null): Promise<boolean> {
    busy.value = finding.fingerprint
    try {
      const { approval } = await approveFinding(finding.fingerprint, comment)
      patchFinding(finding.fingerprint, { approved: true, approval })
      notify('Проблема одобрена', 'success')
      return true
    } catch (err) {
      await handleStale(err, 'Проблема уже изменилась или исправлена — проверка обновлена')
      return false
    } finally {
      busy.value = null
    }
  }

  /**
   * Одобряет сразу несколько проблем одним комментарием. Список режется на части по APPROVAL_BATCH_LIMIT (предел одного запроса) и уходит
   * по очереди; проблемы, которых уже нет или которые изменились, сервер не одобряет, а возвращает — тогда проверка перечитывается.
   * true — что-то одобрено (окно комментария можно закрывать); при сбое посреди списка уже одобренное остаётся одобренным, а причина
   * и число одобренных показываются сообщением.
   */
  async function approveMany(items: ConsistencyFinding[], comment: string | null): Promise<boolean> {
    busy.value = BATCH_BUSY
    let approved = 0
    let already = 0
    let stale = 0
    try {
      for (let start = 0; start < items.length; start += APPROVAL_BATCH_LIMIT) {
        const chunk = items.slice(start, start + APPROVAL_BATCH_LIMIT)
        const result = await approveFindings(
          chunk.map((item) => item.fingerprint),
          comment,
        )
        approved += result.approved
        already += result.already
        stale += result.missing.length
        for (const [fingerprint, approval] of Object.entries(result.approvals)) patchFinding(fingerprint, { approved: true, approval })
      }
    } catch (err) {
      if (approved + already === 0) {
        await handleStale(err, 'Проблемы уже изменились или исправлены — проверка обновлена')
        return false
      }
      notify(`Одобрено ${approved} из ${items.length}: ${err instanceof Error ? err.message : String(err)}`, 'error')
      return true
    } finally {
      busy.value = null
    }
    const problems = (n: number) => pluralRu(n, ['проблема', 'проблемы', 'проблем'])
    notify(`Одобрено: ${approved} ${problems(approved)}${already ? `, уже были одобрены: ${already}` : ''}`, 'success')
    if (stale > 0) {
      notify(`${stale} ${problems(stale)} уже изменились или исправлены — проверка обновлена`, 'error')
      await load()
    }
    return true
  }

  /** Отзывает одобрение: проблема возвращается в список «требуют внимания». */
  async function revoke(finding: ConsistencyFinding): Promise<void> {
    if (!finding.approval) return
    busy.value = finding.fingerprint
    try {
      await revokeApproval(finding.approval.id)
      patchFinding(finding.fingerprint, { approved: false, approval: null })
      notify('Одобрение отозвано', 'success')
    } catch (err) {
      await handleStale(err, 'Одобрение уже отозвано — проверка обновлена')
    } finally {
      busy.value = null
    }
  }

  function setPage(next: number): void {
    page.value = Math.min(Math.max(1, next), pageCount.value)
  }

  function setPageSize(size: number): void {
    if (!PAGE_SIZE_OPTIONS.includes(size)) return
    page.value = pageAfterSizeChange(page.value, pageSize.value, size)
    pageSize.value = size
  }

  function resetFilters(): void {
    Object.assign(filters, DEFAULT_FILTERS)
  }

  return {
    report,
    loading,
    errorText,
    filters,
    page,
    pageSize,
    pageCount,
    pageItems,
    filtered,
    filtersActive,
    sheets,
    counts,
    busy,
    approve,
    approveMany,
    revoke,
    ruleOptions,
    ruleTitle,
    load,
    setPage,
    setPageSize,
    resetFilters,
  }
}
