// Состояние и правила редактора подинтерфейсов (InterfaceSubinterfacesEditor.vue): выбор VLAN только из свободных VLAN порта/группы,
// автоимя при смене VLAN, предупреждение о недоступном VLAN, раскрытие строк и подсказки. Редактор ничего не знает про API: получает строки и
// отдаёт новый список через `update:modelValue`. Вынесено из компонента без изменения поведения.
import { computed, ref } from 'vue'
import type { SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import type { SearchableSelectOption } from '../components/SearchableSelect.vue'
import { emptySubinterface, reassignSubinterfaceVlan } from '../utils/subinterfaces'
import { vlanLabel } from '../utils/vlan'

/** Что редактору подинтерфейсов нужно от своих входных данных (структурно совпадает с props компонента). */
export interface SubinterfaceRowsProps {
  readonly modelValue: SubinterfaceDraftRow[]
  /** Имя порта-родителя: из него строится подсказка имени «<порт>.<VLAN>». У группы не используется. */
  readonly parentName: string
  /** VLAN, из которых можно выбрать: VLAN, выбранные на порту (у группы — VLAN группы). */
  readonly vlanOptions: VLANDefinition[]
  /** Все известные VLAN (справочник), включая уже недоступные порту. */
  readonly vlanCatalog: VLANDefinition[]
  /** Id VLAN, назначенных устройству: отличает «VLAN снят с устройства» от «VLAN не выбран на порту». */
  readonly deviceVlanIds?: ReadonlySet<string>
  readonly mode: 'port' | 'group'
  readonly readonly: boolean
}

export function useSubinterfaceRows(props: SubinterfaceRowsProps, emit: (event: 'update:modelValue', rows: SubinterfaceDraftRow[]) => void) {
  const isGroup = computed(() => props.mode === 'group')
  const ownerWord = computed(() => (isGroup.value ? 'группы' : 'порта'))
  // Строка вынесена из шаблона: «<порт>.<VLAN>» внутри {{ }} Vue разбирает верно, а Prettier и другие HTML-парсеры принимают за теги.
  const hint = computed(() =>
    isGroup.value
      ? 'Логические интерфейсы портов группы на VLAN группы — каждый порт получает свой «<порт>.<VLAN>» с общими IP-адресами и открытыми портами.'
      : 'Логические интерфейсы порта на одном из его VLAN — со своим IP-адресом, открытыми портами и ролью.',
  )

  const sortedVlans = computed(() => [...props.vlanOptions].sort((a, b) => a.vlan_id - b.vlan_id))
  const vlanById = computed(() => new Map(props.vlanOptions.map((v) => [v.id, v])))
  // Номер и подпись VLAN, в том числе уже недоступного (его нет в vlanOptions, но он есть в справочнике).
  const knownVlanById = computed(() => new Map([...props.vlanCatalog, ...props.vlanOptions].map((v) => [v.id, v])))

  // Какие строки раскрыты (по ключу строки): по умолчанию все свёрнуты.
  const expanded = ref<Set<string>>(new Set())
  function toggleExpand(key: string) {
    const next = new Set(expanded.value)
    if (!next.delete(key)) next.add(key)
    expanded.value = next
  }

  function updateRow(index: number, patch: Partial<SubinterfaceDraftRow>) {
    emit(
      'update:modelValue',
      props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    )
  }

  /** VLAN, уже занятые подинтерфейсами порта, кроме строки `exceptIndex` (свой выбор строки не считается занятым). */
  function usedVlanIds(exceptIndex: number): Set<string> {
    return new Set(props.modelValue.flatMap((row, i) => (i !== exceptIndex && row.vlan_id ? [row.vlan_id] : [])))
  }

  /** VLAN порта, свободные для строки: не заняты соседними подинтерфейсами (уже выбранные ранее скрываются из списка). */
  function freeVlans(index: number): VLANDefinition[] {
    const used = usedVlanIds(index)
    return sortedVlans.value.filter((v) => !used.has(v.id))
  }

  /** Есть ли VLAN, на котором ещё можно создать подинтерфейс: иначе новая строка осталась бы без выбора. */
  const hasFreeVlan = computed(() => {
    const used = new Set(props.modelValue.flatMap((row) => (row.vlan_id ? [row.vlan_id] : [])))
    return sortedVlans.value.some((v) => !used.has(v.id))
  })

  /** VLAN строки больше недоступен для выбора (не выбран на порту / снят с устройства / не входит в VLAN группы): строку не
   * теряем молча — показываем предупреждение, а сохранить её можно, лишь выбрав другой VLAN. */
  function isStaleVlan(row: SubinterfaceDraftRow): boolean {
    return Boolean(row.vlan_id) && !vlanById.value.has(row.vlan_id)
  }

  /** Подпись недоступного VLAN подинтерфейса («10 — Серверы») для предупреждения; пусто, если VLAN нет и в справочнике. */
  function staleVlanLabel(row: SubinterfaceDraftRow): string {
    const vlan = knownVlanById.value.get(row.vlan_id)
    return vlan ? vlanLabel(vlan) : ''
  }

  /** Почему VLAN недоступен: снят с устройства (для порта и группы — одинаково) либо просто не выбран на порту / в группе. */
  function staleReason(row: SubinterfaceDraftRow): 'device' | 'owner' {
    return props.deviceVlanIds && !props.deviceVlanIds.has(row.vlan_id) ? 'device' : 'owner'
  }

  /** Варианты списка VLAN строки: свободные VLAN порта; собственный недоступный VLAN строки показывается пометкой, чтобы поле
   * не выглядело пустым (а предупреждение под строкой объясняет, что делать). */
  function vlanChoices(index: number): SearchableSelectOption[] {
    const options = freeVlans(index).map((v) => ({ value: v.id, label: vlanLabel(v) }))
    const row = props.modelValue[index]
    if (row && isStaleVlan(row)) {
      const label = staleVlanLabel(row)
      options.unshift({ value: row.vlan_id, label: label ? `${label} — недоступен` : 'VLAN недоступен' })
    }
    return options
  }

  /** Образец имени для шаблона группы: «‹порт›.10». */
  function groupNamePattern(row: SubinterfaceDraftRow): string {
    const vlan = knownVlanById.value.get(row.vlan_id)
    return `‹порт›.${vlan ? vlan.vlan_id : '‹VLAN›'}`
  }

  function addRow() {
    if (props.readonly) return
    emit('update:modelValue', [...props.modelValue, emptySubinterface(props.parentName)])
  }

  function removeRow(index: number) {
    emit(
      'update:modelValue',
      props.modelValue.filter((_, i) => i !== index),
    )
  }

  // При выборе VLAN имя подставляется само («Gi0/0.10»), но только если пользователь его не правил:
  // имя пустое либо совпадает с подсказкой для предыдущего VLAN — иначе не затираем введённое вручную.
  // (То же правило пересчитывает автоимена при переименовании порта — utils/subinterfaces.ts:renameSubinterfacesForPort.)
  function onVlanChange(index: number, vlanId: string) {
    const row = props.modelValue[index]
    if (!row) return
    const next = vlanById.value.get(vlanId)
    // Очищено поле («крестик» списка): VLAN снимается, имя не трогаем. У шаблона группы имени нет.
    if (!next || isGroup.value) {
      updateRow(index, { vlan_id: vlanId })
      return
    }
    // Прежний VLAN ищем и в справочнике: у подинтерфейса на снятом VLAN он уже не в vlanOptions, но автоимя
    // («Gi0/0.20») при переносе на другой VLAN должно обновиться так же, как при обычной смене.
    const { vlan_id, name } = reassignSubinterfaceVlan(row, props.parentName, knownVlanById.value.get(row.vlan_id), next)
    updateRow(index, { vlan_id, name })
  }

  /** Сводка адресов для свёрнутого столбца: «10.0.10.1/24, 10.0.10.2/24»; пустые строки формы не показываются. */
  function ipSummary(row: SubinterfaceDraftRow): string {
    return row.ips
      .filter((ip) => ip.ip_address.trim())
      .map((ip) => (ip.prefix_length !== '' ? `${ip.ip_address.trim()}/${ip.prefix_length}` : ip.ip_address.trim()))
      .join(', ')
  }

  const emptyText = computed(() => {
    if (props.vlanOptions.length) return 'Подинтерфейсы не добавлены'
    return isGroup.value
      ? 'Подинтерфейсы не добавлены. Чтобы создать, задайте режим порта и VLAN группы.'
      : 'Подинтерфейсы не добавлены. Чтобы создать, выберите VLAN порта.'
  })
  const addTitle = computed(() => {
    if (!props.vlanOptions.length) return `Для ${isGroup.value ? 'группы' : 'порта'} не выбраны VLAN — подинтерфейс создаётся на одном из них`
    if (!hasFreeVlan.value) return `Все VLAN ${ownerWord.value} уже использованы подинтерфейсами`
    return undefined
  })

  return {
    isGroup,
    ownerWord,
    hint,
    expanded,
    toggleExpand,
    updateRow,
    freeVlans,
    hasFreeVlan,
    isStaleVlan,
    staleVlanLabel,
    staleReason,
    vlanChoices,
    groupNamePattern,
    addRow,
    removeRow,
    onVlanChange,
    ipSummary,
    emptyText,
    addTitle,
  }
}
