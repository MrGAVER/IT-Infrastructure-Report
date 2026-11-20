// Список дашборда «Стеки устройств»: сводка по стекам (из списка стеков и реестра устройств), поиск, постраничный вывод, раскрытие
// строк и подгрузка общих VLAN раскрытых строк текущей страницы. Вынесено из DeviceStacksView.vue без изменения поведения.
import { computed, ref, watch } from 'vue'
import { useDeviceStacksStore } from '../stores/deviceStacks'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { usePagedList } from './usePagedList'
import { useStackSharedVlans } from './useStackSharedVlans'
import { buildStackSummaries, stackSearchTexts, stackStats } from '../utils/stackSummary'
import { filterBySearch } from '../utils/textSearch'
import { deviceModelLabel, devicePlaceLabel } from '../utils/deviceLabels'

export function useDeviceStacksList() {
  const stacks = useDeviceStacksStore()
  const devices = useDevicesStore()
  const catalogs = useCatalogsStore()

  const summaries = computed(() =>
    buildStackSummaries(stacks.all, devices.all, { model: (d) => deviceModelLabel(catalogs, d), place: (d) => devicePlaceLabel(catalogs, d) }),
  )
  const stats = computed(() => stackStats(summaries.value))

  // Поиск — по названию и описанию стека и по тому, что показано о его составе (см. stackSearchTexts); несколько слов сужают выбор.
  const search = ref('')
  const filtered = computed(() => filterBySearch(summaries.value, search.value, stackSearchTexts))
  const isSearching = computed(() => search.value.trim() !== '')

  const { page, pageSize, pageSizeOptions, pageCount, pageItems, total, rangeFrom, rangeTo, setPage, setPageSize, resetPage } = usePagedList(
    () => filtered.value,
    { listId: 'deviceStacks' },
  )
  watch(search, () => resetPage())

  // Раскрытые строки: id стеков. Набор общий для всех страниц, поэтому раскрытие не теряется при переходе по страницам.
  const expanded = ref(new Set<string>())
  function isExpanded(id: string): boolean {
    return expanded.value.has(id)
  }
  function toggle(id: string) {
    if (expanded.value.has(id)) expanded.value.delete(id)
    else expanded.value.add(id)
  }
  const allExpanded = computed(() => filtered.value.length > 0 && filtered.value.every((s) => expanded.value.has(s.stack.id)))
  function toggleAll() {
    const ids = filtered.value.map((s) => s.stack.id)
    if (allExpanded.value) for (const id of ids) expanded.value.delete(id)
    else for (const id of ids) expanded.value.add(id)
  }

  // Общие VLAN стека не входят в реестр устройств, поэтому подгружаются отдельным запросом на стек — только для раскрытых строк
  // текущей страницы (см. composables/useStackSharedVlans.ts). По ним поиск не ведётся: они появляются после раскрытия строки.
  const stackVlans = useStackSharedVlans(() => pageItems.value.filter((s) => expanded.value.has(s.stack.id)).map((s) => s.stack.id))

  return {
    summaries,
    stats,
    search,
    filtered,
    isSearching,
    page,
    pageSize,
    pageSizeOptions,
    pageCount,
    pageItems,
    total,
    rangeFrom,
    rangeTo,
    setPage,
    setPageSize,
    isExpanded,
    toggle,
    allExpanded,
    toggleAll,
    stackVlans,
  }
}
