<script setup lang="ts">
// Редактор подинтерфейсов ОДНОГО порта устройства или ОДНОЙ группы портов — логических интерфейсов на отдельном VLAN со
// своими IP-адресами, открытыми портами и ролью (как у маршрутизаторов и межсетевых экранов: Gi0/0.10 на VLAN 10 с адресом
// 10.0.10.1/24). Как и OpenPortListEditor.vue / VmIpListEditor.vue, компонент ничего не знает про API и сервер: получает
// список строк, отдаёт новый список через `update:modelValue`; сохранение выполняет форма устройства вместе с портами одним
// запросом (api/deviceInterfaces.ts:persistDeviceInterfaces), а проверка при сохранении — общая с формой функция
// utils/subinterfaces.ts:validateSubinterfaceRows. Здесь только подсказки по ходу ввода.
//
// Вид — таблица, как «Список интерфейсов»: «Имя», «VLAN», «Управление», «Данные» и разворачиваемый столбец «IP-адреса / маски».
// Столбец по умолчанию свёрнут и показывает адреса с масками (10.0.10.1/24); раскрытая строка — формы IP-адресов и открытых
// портов подинтерфейса (и описание).
//
// Правила, которые редактор помогает соблюсти (серверные зеркальны — backend/app/services/crud/subinterfaces.py):
//  • VLAN подинтерфейса выбирается ТОЛЬКО из VLAN, выбранных на этом порту (vlanOptions; у группы — из VLAN группы) и
//    только из ещё не занятых другими подинтерфейсами порта: на порту VLAN используется один раз, уже выбранные в списке
//    не показываются (собственный выбор строки остаётся). Список — SearchableSelect: ищется по номеру, имени и домену VLAN.
//    Он в режиме floating: таблица лежит в контейнере с overflow-x: auto, который обрезал бы выпадающий список по высоте
//    (список уходил под край блока, и блок приходилось прокручивать) — панель выводится поверх, в <body>;
//  • имя подинтерфейса уникально на устройстве (это проверяет форма при сохранении).
//
// mode='group': подинтерфейс группы — шаблон, который записывается в каждый порт группы с именем `<порт>.<номер VLAN>`, поэтому
// своего имени у шаблона нет (в столбце «Имя» — образец). readonly — подинтерфейсы заданы группой портов, здесь только просмотр.
import { computed, ref } from 'vue'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import ScrollableTableWrap from './ScrollableTableWrap.vue'
import type { InterfaceIpDraftRow, OpenPortDraftRow, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import { emptySubinterface, reassignSubinterfaceVlan } from '../utils/subinterfaces'
import { vlanLabel } from '../utils/vlan'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

const props = withDefaults(
  defineProps<{
    modelValue: SubinterfaceDraftRow[]
    /** Имя порта-родителя: из него строится подсказка имени «<порт>.<VLAN>». У группы не используется. */
    parentName: string
    /** VLAN, из которых можно выбрать: VLAN, выбранные на порту (у группы — VLAN группы). */
    vlanOptions: VLANDefinition[]
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    /** Порог сворачивания списка открытых портов подинтерфейса (общий порог из «Настроек»); не передан — без сворачивания. */
    collapseAfter?: number
    /** Все известные VLAN (справочник), включая уже недоступные порту: по ним для подинтерфейса на снятом VLAN
     * известен номер (подпись в предупреждении, пересчёт автоимени при переносе). Без него — только vlanOptions. */
    vlanCatalog?: VLANDefinition[]
    /** Id VLAN, назначенных устройству: отличает «VLAN снят с устройства» от «VLAN не выбран на порту» в предупреждении. */
    deviceVlanIds?: ReadonlySet<string>
    mode?: 'port' | 'group'
    /** Подинтерфейсы заданы группой портов: редактирование выключено. */
    readonly?: boolean
    /** Пояснение над таблицей (например, «Подинтерфейсы заданы группой «X»…»). */
    readonlyNote?: string
  }>(),
  { protocolPortCatalog: () => [], vlanCatalog: () => [], mode: 'port', readonly: false, readonlyNote: '' },
)
const emit = defineEmits<{ 'update:modelValue': [rows: SubinterfaceDraftRow[]] }>()

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

// Перенос подинтерфейса с недоступного VLAN на выбранный одним действием: та же смена VLAN, что и в основной строке
// (с пересчётом автоимени), после чего предупреждение исчезает. Список сразу возвращается в исходное положение.
function moveToVlan(index: number, event: Event) {
  const select = event.target as HTMLSelectElement
  const vlanId = select.value
  select.value = ''
  if (vlanId) onVlanChange(index, vlanId)
}

function addIp(index: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: [...row.ips, { ip_address: '', prefix_length: '', purpose: '' }] })
}

function removeIp(index: number, ipIndex: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.filter((_, j) => j !== ipIndex) })
}

function updateIp(index: number, ipIndex: number, patch: Partial<InterfaceIpDraftRow>) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.map((ip, j) => (j === ipIndex ? { ...ip, ...patch } : ip)) })
}

function updateOpenPorts(index: number, rows: OpenPortDraftRow[]) {
  updateRow(index, { open_ports: rows })
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
</script>

<template>
  <div class="sub-block">
    <div class="sub-head">
      <div class="sub-title">
        <b>Подинтерфейсы</b>
        <span class="hint">
          {{ hint }}
        </span>
      </div>
      <button v-if="!readonly" type="button" class="btn btn-secondary" :disabled="!vlanOptions.length || !hasFreeVlan" :title="addTitle" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Подинтерфейс
      </button>
    </div>

    <div v-if="readonlyNote" class="group-lock">{{ readonlyNote }}</div>

    <div v-if="!modelValue.length" class="empty">{{ emptyText }}</div>

    <ScrollableTableWrap v-else label="Подинтерфейсы">
      <table class="sub-table">
        <thead>
          <tr>
            <th>Имя</th>
            <th class="col-vlan">VLAN</th>
            <th class="col-check">Управление</th>
            <th class="col-check">Данные</th>
            <th>IP-адреса / маски</th>
            <th v-if="!readonly" class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(sub, i) in modelValue" :key="sub.key">
            <tr class="sub-row">
              <td>
                <span v-if="isGroup" class="name-pattern">{{ groupNamePattern(sub) }}</span>
                <input
                  v-else
                  type="text"
                  class="cell-input"
                  :value="sub.name"
                  :disabled="readonly"
                  placeholder="Например, Gi0/0.10"
                  maxlength="100"
                  aria-label="Имя подинтерфейса"
                  @input="updateRow(i, { name: ($event.target as HTMLInputElement).value })"
                />
              </td>
              <td class="col-vlan">
                <SearchableSelect
                  class="vlan-select"
                  :class="{ 'is-stale': isStaleVlan(sub) }"
                  aria-label="VLAN подинтерфейса"
                  :model-value="sub.vlan_id"
                  :options="vlanChoices(i)"
                  :disabled="readonly"
                  floating
                  placeholder="— выберите VLAN —"
                  :empty-text="`Все VLAN ${ownerWord} уже использованы`"
                  @update:model-value="(v) => onVlanChange(i, v)"
                />
              </td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="sub.is_management"
                  :disabled="readonly"
                  aria-label="Подинтерфейс: управление"
                  @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })"
                />
              </td>
              <td class="col-check">
                <input
                  type="checkbox"
                  :checked="sub.is_data_transfer"
                  :disabled="readonly"
                  aria-label="Подинтерфейс: передача данных"
                  @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })"
                />
              </td>
              <td>
                <button
                  type="button"
                  class="expand-toggle"
                  :aria-expanded="expanded.has(sub.key)"
                  aria-label="Показать IP-адреса и открытые порты подинтерфейса"
                  @click="toggleExpand(sub.key)"
                >
                  <span v-if="ipSummary(sub)" v-truncate-tooltip class="ip-summary">{{ ipSummary(sub) }}</span>
                  <span v-else class="ip-none">нет IP</span>
                  <span v-if="sub.open_ports.length" class="ports-count">· портов: {{ sub.open_ports.length }}</span>
                  <svg class="icon chev" :class="{ open: expanded.has(sub.key) }"><use href="/icons.svg#i-chevd" /></svg>
                </button>
              </td>
              <td v-if="!readonly" class="col-actions">
                <button type="button" class="icon-btn danger" aria-label="Удалить подинтерфейс" @click="removeRow(i)">
                  <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                </button>
              </td>
            </tr>

            <tr v-if="isStaleVlan(sub)" class="sub-warn-row">
              <td :colspan="readonly ? 5 : 6">
                <div class="sub-warn" role="alert">
                  <span v-if="staleReason(sub) === 'device'">
                    VLAN этого подинтерфейса<template v-if="staleVlanLabel(sub)"> ({{ staleVlanLabel(sub) }})</template> больше не назначен устройству.
                    Перенесите подинтерфейс на другой VLAN или удалите его — иначе сохранить не получится.
                  </span>
                  <span v-else>
                    VLAN этого подинтерфейса<template v-if="staleVlanLabel(sub)"> ({{ staleVlanLabel(sub) }})</template>
                    {{ isGroup ? 'не входит в VLAN группы' : 'не выбран на этом порту' }}. Перенесите подинтерфейс на другой VLAN или удалите его — иначе
                    сохранить не получится.
                  </span>
                  <select
                    v-if="!readonly"
                    class="sub-move"
                    aria-label="Перенести подинтерфейс на VLAN"
                    :disabled="!freeVlans(i).length"
                    :title="freeVlans(i).length ? undefined : `Нет свободных VLAN ${ownerWord} — выберите VLAN или удалите подинтерфейс`"
                    @change="moveToVlan(i, $event)"
                  >
                    <option value="">Перенести на VLAN…</option>
                    <option v-for="v in freeVlans(i)" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
                  </select>
                </div>
              </td>
            </tr>

            <tr v-if="expanded.has(sub.key)" class="sub-detail-row">
              <td :colspan="readonly ? 5 : 6">
                <div class="sub-detail">
                  <label class="sub-field">
                    <span>Описание</span>
                    <input
                      type="text"
                      :value="sub.description"
                      :disabled="readonly"
                      placeholder="Необязательно"
                      aria-label="Описание подинтерфейса"
                      @input="updateRow(i, { description: ($event.target as HTMLInputElement).value })"
                    />
                  </label>

                  <div class="sub-ips">
                    <div class="sub-ips-head">
                      <b>IP-адреса подинтерфейса</b>
                      <button v-if="!readonly" type="button" class="btn btn-secondary" @click="addIp(i)">
                        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                        IP-адрес
                      </button>
                    </div>
                    <div v-if="!sub.ips.length" class="empty">IP-адреса не добавлены</div>
                    <div v-for="(ip, j) in sub.ips" :key="ip.id ?? j" class="ip-row">
                      <input
                        type="text"
                        placeholder="IP-адрес"
                        aria-label="IP-адрес подинтерфейса"
                        :value="ip.ip_address"
                        :disabled="readonly"
                        @input="updateIp(i, j, { ip_address: ($event.target as HTMLInputElement).value })"
                      />
                      <input
                        type="number"
                        min="0"
                        max="32"
                        placeholder="Префикс"
                        aria-label="Префикс"
                        :value="ip.prefix_length"
                        :disabled="readonly"
                        @input="updateIp(i, j, { prefix_length: ($event.target as HTMLInputElement).value })"
                      />
                      <input
                        type="text"
                        placeholder="Назначение"
                        aria-label="Назначение IP-адреса"
                        :value="ip.purpose"
                        :disabled="readonly"
                        @input="updateIp(i, j, { purpose: ($event.target as HTMLInputElement).value })"
                      />
                      <button v-if="!readonly" type="button" class="icon-btn danger" aria-label="Удалить IP подинтерфейса" @click="removeIp(i, j)">
                        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                      </button>
                    </div>
                  </div>

                  <OpenPortListEditor
                    :model-value="sub.open_ports"
                    :catalog-entries="protocolPortCatalog"
                    :collapse-after="collapseAfter"
                    :readonly="readonly"
                    sorted-unique
                    @update:model-value="(v) => updateOpenPorts(i, v)"
                  />
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </ScrollableTableWrap>
  </div>
</template>

<style scoped>
.sub-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.sub-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.sub-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sub-title b,
.sub-ips-head b {
  font-size: 11.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.group-lock {
  font-size: 11px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 2px 0;
}
/* Таблица подинтерфейсов — тот же вид, что у «Списка интерфейсов» (DeviceInterfacesEditor.vue). */
.sub-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.sub-table th {
  text-align: left;
  font-weight: 600;
  color: var(--ink-muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  padding: 0 6px 6px;
  white-space: nowrap;
}
.sub-table td {
  padding: 4px 6px;
  vertical-align: middle;
  border-top: 1px solid var(--border);
}
.sub-table .col-vlan {
  min-width: 190px;
}
.sub-table .col-check,
.sub-table .col-actions {
  width: 1%;
  white-space: nowrap;
  text-align: center;
}
.sub-table .col-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.cell-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 7px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 110px;
  box-sizing: border-box;
}
.name-pattern {
  color: var(--ink-muted);
  font-size: 12px;
  white-space: nowrap;
}
.vlan-select.is-stale :deep(input) {
  border-color: var(--status-crit);
}
.expand-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 4px 2px;
  font-size: 11.5px;
  color: var(--ink);
  cursor: pointer;
  white-space: nowrap;
  max-width: 100%;
}
.expand-toggle:hover .chev {
  color: var(--ink);
}
.ip-none,
.ports-count {
  color: var(--ink-muted);
}
.ip-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform 0.15s;
  flex-shrink: 0;
  color: var(--ink-muted);
}
.chev.open {
  transform: rotate(180deg);
}
.sub-warn-row td,
.sub-detail-row td {
  border-top: none;
  padding-top: 0;
}
.sub-warn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 11.5px;
  color: var(--status-crit);
}
.sub-move {
  background: var(--surface-2);
  border: 1px solid var(--status-crit);
  border-radius: var(--r-s);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
.sub-detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.sub-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
  min-width: 0;
}
.sub-field input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
}
.sub-ips {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-ips-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ip-row {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 720px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
