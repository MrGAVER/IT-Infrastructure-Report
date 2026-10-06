<script setup lang="ts">
// SearchableSelect.vue (п.4) — замена нативному <select v-model="x"> с возможностью отфильтровать
// опции вводом текста. Используется как v-model, но принимает options в собственном плоском
// формате { value, label, group? }, а не "сырые" CatalogItem { id, name } — так компонент не
// завязан на форму каталогов конкретно этого приложения и группировку (optgroup) можно выразить
// тем же способом, что и обычный список (см. modelSelectOptions в DeviceFormModal.vue).
//
// Сознательно НЕ реализует нативную HTML5-валидацию (required) — этот компонент не <select>,
// браузер не покажет свой "заполните это поле" пузырь. Формы, куда он подключается, и так уже
// проверяют обязательные fk-поля вручную перед отправкой (см. submit() в DeviceFormModal.vue и
// аналогичных) — доп. required-проп добавил бы API, которое ничего не делает, и создал бы
// иллюзию валидации там, где её на самом деле нет.
//
// Позиционирование поповера — как в HelpTip.vue (position: absolute в position: relative
// обёртке, без Teleport): тот же осознанный компромисс с тем же риском обрезки внутри
// overflow:auto контейнера (например, длинной модалки) — консистентно с уже существующим
// паттерном в этом кодбейзе, а не отдельное решение только для этого компонента.
//
// Режим remote — для списков, которые слишком велики, чтобы грузить их целиком (например, устройства реестра):
// компонент не фильтрует options сам, а сообщает введённый текст событием search (при открытии — пустая
// строка), и родитель подставляет в options ответ сервера. loading показывает ожидание ответа, hint —
// пояснение под списком («показаны первые 50 из 312»). Подпись текущего выбора родитель обязан держать
// в options сам: после поиска её может не оказаться среди найденного.
//
// @example
// <SearchableSelect
//   v-model="form.room_id"
//   :options="(catalogs.items['rooms'] ?? []).map((r) => ({ value: r.id, label: r.name }))"
//   placeholder="— не выбрано —"
// />
//
// <SearchableSelect v-model="deviceId" remote :options="found" :loading="busy" @search="runSearch" />
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { vTruncateTooltip } from '../directives/truncateTooltip'

export interface SearchableSelectOption {
  value: string
  label: string
  /** Опции с одинаковым group рендерятся под одним заголовком — аналог <optgroup>. Порядок
   * групп — по первому появлению в options, ничего не пересортировывается. */
  group?: string
  /** Дополнительный текст, по которому опция находится при вводе, но который не показывается (например,
   * тип устройства у модели: «коммутатор cisco» найдёт модель, в подписи которой есть только производитель
   * и название). Подпись и searchText ищутся вместе. */
  searchText?: string
}

/** Слова запроса без учёта регистра; пустой запрос — пустой список (фильтра нет). */
function searchTokens(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean)
}

/** Опция подходит, если КАЖДОЕ слово запроса встречается в подписи или в searchText — слова могут идти
 * в любом порядке и не подряд («cisco 2960» находит «Cisco WS-C2960-48TD-L»). */
function matchesSearch(option: SearchableSelectOption, tokens: readonly string[]): boolean {
  if (!tokens.length) return true
  const haystack = `${option.label} ${option.searchText ?? ''}`.toLowerCase()
  return tokens.every((token) => haystack.includes(token))
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: SearchableSelectOption[]
    placeholder?: string
    disabled?: boolean
    /** Опции приходят от родителя по запросу: локальной фильтрации нет, ввод уходит событием search. */
    remote?: boolean
    /** Только для remote: ответ на последний поиск ещё не пришёл. */
    loading?: boolean
    /** Строка-пояснение под списком опций (например, что показана только часть найденного). */
    hint?: string
  }>(),
  { placeholder: '— не выбрано —', disabled: false, remote: false, loading: false, hint: '' },
)
const emit = defineEmits<{ 'update:modelValue': [value: string]; search: [query: string] }>()

const open = ref(false)
const query = ref('')
const highlightedIndex = ref(0)
const rootEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)

const selectedOption = computed(() => props.options.find((o) => o.value === props.modelValue) ?? null)

const filteredOptions = computed(() => {
  if (props.remote) return props.options // фильтрует сервер
  const tokens = searchTokens(query.value)
  if (!tokens.length) return props.options
  return props.options.filter((o) => matchesSearch(o, tokens))
})

/** Плоский список с индексом для клавиатурной навигации, сгруппированный для отображения —
 * группировка только визуальная, ArrowUp/ArrowDown/Enter работают по единому плоскому индексу,
 * не завязанному на границы групп. */
const groupedOptions = computed(() => {
  const groups: { group: string | null; options: (SearchableSelectOption & { flatIndex: number })[] }[] = []
  filteredOptions.value.forEach((opt, flatIndex) => {
    const key = opt.group ?? null
    let bucket = groups.find((g) => g.group === key)
    if (!bucket) {
      bucket = { group: key, options: [] }
      groups.push(bucket)
    }
    bucket.options.push({ ...opt, flatIndex })
  })
  return groups
})

// Пока поповер закрыт, поле показывает подпись текущего выбора (или placeholder) — как обычный
// select. Открывается — очищаем query, чтобы сразу увидеть весь список, как при клике на select.
// Подпись пересчитывается и при появлении/смене подписи выбранной опции, а не только при смене
// самого значения: значение может быть выставлено РАНЬШЕ, чем опция с таким value доехала в
// options (например, только что созданная через "+" запись, которую родитель ещё догружает из
// стора) — без второго источника поле осталось бы пустым, хотя значение выбрано.
watch(
  () => [props.modelValue, selectedOption.value?.label] as const,
  () => {
    if (!open.value) query.value = selectedOption.value?.label ?? ''
  },
  { immediate: true },
)
watch(filteredOptions, () => {
  highlightedIndex.value = 0
})

function openDropdown() {
  if (props.disabled || open.value) return
  open.value = true
  query.value = ''
  if (props.remote) emit('search', '')
  highlightedIndex.value = Math.max(
    0,
    filteredOptions.value.findIndex((o) => o.value === props.modelValue),
  )
}
function closeDropdown() {
  open.value = false
  query.value = selectedOption.value?.label ?? ''
}
function onInput(event: Event) {
  query.value = (event.target as HTMLInputElement).value
  if (props.remote) emit('search', query.value)
}
function selectOption(opt: SearchableSelectOption) {
  emit('update:modelValue', opt.value)
  closeDropdown()
  inputEl.value?.blur()
}
function clearSelection() {
  emit('update:modelValue', '')
  query.value = ''
  inputEl.value?.focus()
}

function onDocumentClick(event: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(event.target as Node)) closeDropdown()
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

function scrollHighlightedIntoView() {
  nextTick(() => {
    const el = rootEl.value?.querySelector('.ss-option.highlighted')
    // jsdom (тестовое окружение) не реализует scrollIntoView — защитная проверка на существование
    // метода нужна не только браузерной совместимости ради, но и чтобы тесты не падали на этом.
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' })
  })
}
function onArrowDown() {
  if (!open.value) {
    openDropdown()
    return
  }
  highlightedIndex.value = Math.min(highlightedIndex.value + 1, filteredOptions.value.length - 1)
  scrollHighlightedIntoView()
}
function onArrowUp() {
  if (!open.value) {
    openDropdown()
    return
  }
  highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
  scrollHighlightedIntoView()
}
function onEnter() {
  if (!open.value) return
  const opt = filteredOptions.value[highlightedIndex.value]
  if (opt) selectOption(opt)
}
</script>

<template>
  <div ref="rootEl" class="searchable-select" :class="{ open, disabled }">
    <div class="ss-input-row">
      <input
        ref="inputEl"
        type="text"
        :value="query"
        :placeholder="placeholder"
        :disabled="disabled"
        autocomplete="off"
        @focus="openDropdown"
        @click="openDropdown"
        @input="onInput"
        @keydown.down.prevent="onArrowDown"
        @keydown.up.prevent="onArrowUp"
        @keydown.enter.prevent="onEnter"
        @keydown.esc="closeDropdown"
      />
      <button
        v-if="modelValue && !disabled"
        type="button"
        class="ss-clear"
        aria-label="Очистить выбор"
        @mousedown.prevent="clearSelection"
      >
        <svg class="icon"><use href="/icons.svg#i-x" /></svg>
      </button>
      <svg class="icon ss-chev" :class="{ open }"><use href="/icons.svg#i-chevd" /></svg>
    </div>

    <div v-if="open" class="ss-panel" role="listbox">
      <div v-if="!filteredOptions.length" class="ss-empty">{{ loading ? 'Загрузка…' : 'Ничего не найдено' }}</div>
      <template v-for="g in groupedOptions" :key="g.group ?? '__ungrouped'">
        <div v-if="g.group" class="ss-group-label">{{ g.group }}</div>
        <button
          v-for="opt in g.options"
          :key="opt.value"
          type="button"
          class="ss-option"
          :class="{ highlighted: opt.flatIndex === highlightedIndex, selected: opt.value === modelValue }"
          v-truncate-tooltip="opt.label"
          @mousedown.prevent="selectOption(opt)"
          @mouseenter="highlightedIndex = opt.flatIndex"
        >
          {{ opt.label }}
        </button>
      </template>
      <div v-if="filteredOptions.length && (loading || hint)" class="ss-hint">{{ loading ? 'Загрузка…' : hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.searchable-select {
  position: relative;
  min-width: 0;
}
.ss-input-row {
  position: relative;
  display: flex;
  align-items: center;
}
.ss-input-row input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 52px 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
}
.searchable-select.disabled .ss-input-row input {
  opacity: 0.6;
  cursor: not-allowed;
}
.ss-input-row input:focus {
  outline: none;
  border-color: var(--ink-muted);
}
.ss-clear {
  position: absolute;
  right: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
}
.ss-clear:hover {
  color: var(--ink);
}
.ss-clear .icon {
  width: 12px;
  height: 12px;
}
.ss-chev {
  position: absolute;
  right: 9px;
  width: 13px;
  height: 13px;
  color: var(--ink-muted);
  pointer-events: none;
  transition: transform 0.12s ease;
}
.ss-chev.open {
  transform: rotate(180deg);
}
.ss-panel {
  position: absolute;
  z-index: 85;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--surface-1, var(--surface));
  box-shadow: var(--shadow-m, 0 8px 24px rgba(0, 0, 0, 0.35));
  padding: 4px;
}
.ss-empty {
  padding: 8px 9px;
  font-size: 12px;
  color: var(--ink-muted);
}
.ss-hint {
  padding: 6px 9px 3px;
  font-size: 11px;
  color: var(--ink-muted);
}
.ss-group-label {
  padding: 6px 9px 3px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
}
.ss-option {
  display: block;
  width: 100%;
  text-align: left;
  padding: 7px 9px;
  border: none;
  border-radius: var(--r-s);
  background: transparent;
  color: var(--ink);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ss-option.highlighted {
  background: var(--surface-2);
}
.ss-option.selected {
  font-weight: 600;
}
</style>
