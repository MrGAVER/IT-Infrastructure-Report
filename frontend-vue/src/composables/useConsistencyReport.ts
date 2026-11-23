// Состояние экрана «Проверка данных»: загрузка находок и каталога правил, фильтры и страницы.
// Находки читаются одним запросом (api/consistency.ts), фильтрация и разбиение на страницы — на клиенте.
import { computed, reactive, ref, watch } from 'vue'
import { fetchConsistency, fetchConsistencyRules } from '../api/consistency'
import type { ConsistencyReport, ConsistencyRule } from '../api/consistency'
import { DEFAULT_FILTERS, filterFindings, hasActiveFilters, sheetsWithFindings } from '../utils/consistencyFilter'
import type { ConsistencyFilters } from '../utils/consistencyFilter'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, pageAfterSizeChange } from '../utils/pageSize'

export function useConsistencyReport() {
  const report = ref<ConsistencyReport | null>(null)
  const rules = ref<ConsistencyRule[]>([])
  const loading = ref(false)
  const errorText = ref('')
  const filters = reactive<ConsistencyFilters>({ ...DEFAULT_FILTERS })
  const page = ref(1)
  // Размер страницы здесь не запоминается: список настроек запоминаемых списков задаёт сервер (preferences), а этот экран — справочный.
  const pageSize = ref(DEFAULT_PAGE_SIZE)

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
    ruleOptions,
    ruleTitle,
    load,
    setPage,
    setPageSize,
    resetFilters,
  }
}
