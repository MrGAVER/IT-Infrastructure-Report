<script setup lang="ts">
// Блок «Подключение» в раскрытой строке порта (DeviceInterfacesEditor.vue): порт подключается к порту
// другого устройства прямо при создании/редактировании устройства — без перехода на экран
// «Подключения». Выбор в два шага (устройство → порт), как в ConnectionFormModal.vue, плюс тип физической
// линии связи и описание.
//
// Компонент только редактирует черновик (v-model: InterfaceConnectionDraft | null) и ничего не сохраняет:
// подключение уходит на сервер вместе с портами одним PUT (см. api/deviceInterfaces.ts:persistDeviceInterfaces).
// Это нужно, потому что у нового порта ещё нет id — отдельным запросом подключение создать нельзя.
// Сам компонент загружает только два вида данных, оба у сервера (api/deviceConnectivity.ts): устройства-соседей —
// поиском со страницами, а не из полного списка устройств реестра, — и свободные порты выбранного соседа;
// занятость портов считает сервер, а не клиент по общим спискам с потолком в 1000 записей.
//
// Соседний порт — порт другого устройства (из сохранённых) или, если родитель передал selfPorts, ДРУГОЙ порт
// этого же устройства, в том числе ещё не сохранённый: у него нет id, поэтому на строку формы ссылаются по
// стабильному ключу (peer_row_key), а сервер получает номер элемента массива interfaces (peer_row). Из списка
// исключены порты, уже занятые активным подключением, и порты, выбранные в соседних строках этой же формы;
// порт, выбранный в этой строке, остаётся доступным, чтобы подключение можно было открыть и изменить его тип
// или описание. Порт, подключение которого переставляется или снимается в этой же форме (freedPeerIds),
// считается свободным: так порты можно поменять местами, не сохраняя форму между шагами.
//
// Расхождение конфигурации (Управление / Передача данных / режим порта / «Все VLAN») с портом соседа показывается
// сразу — до сохранения. Сохранению оно не мешает: как и у подключения, созданного на экране
// «Подключения», расхождение отображается там со статусом «расхождение» до решения или одобрения.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { DEVICE_OPTIONS_PAGE_SIZE, fetchAllFreeInterfaces, fetchDeviceOptionsPage, type DeviceOption, type FreeInterface } from '../api/deviceConnectivity'
import type { InterfaceConnectionDraft } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import {
  SELF_DEVICE,
  connectionConfigDiffKinds,
  connectionConfigDiffs,
  emptyConnectionDraft,
  peerRef,
  type ConfigDiffKind,
  type PeerConfigTarget,
  type PortConfigLike,
  type SelfPortCandidate,
} from '../utils/interfaceConnections'
import SearchableSelect from './SearchableSelect.vue'

const props = withDefaults(
  defineProps<{
    modelValue: InterfaceConnectionDraft | null
    /** Устройство, чьи порты редактируются (null — новое): его порты в списке соседей не показываются. */
    deviceId: string | null
    /** Подпись редактируемого устройства для пункта «это устройство» (имя или серийный номер в форме). */
    deviceLabel?: string
    /** Текущая конфигурация порта этой строки — для сравнения с портом соседа. */
    config: PortConfigLike
    /** Порты соседей, уже выбранные в ДРУГИХ строках формы (peerRef: id порта или `row:<key>`). */
    takenPeerIds?: ReadonlySet<string>
    /** Другие порты этого же устройства, доступные в роли соседа. Не задано — выбрать сосед на этом же
     * устройстве нельзя (его нет в списке устройств). */
    selfPorts?: readonly SelfPortCandidate[]
    /** Порты других устройств, которые этой формой освобождаются (подключение снято или переставлено). */
    freedPeerIds?: ReadonlySet<string>
    /** Родитель применяет конфигурацию (запрос или каскад в процессе) — кнопки «Применить…» недоступны. */
    applying?: boolean
    /** Счётчик изменений портов соседей, сделанных родителем (применили конфигурацию соседу): при росте порты
     * соседа перечитываются с сервера, иначе панель расхождения показывала бы уже устранённое. */
    peersVersion?: number
  }>(),
  { takenPeerIds: () => new Set<string>(), selfPorts: undefined, freedPeerIds: () => new Set<string>(), applying: false, peersVersion: 0 },
)
const emit = defineEmits<{
  'update:modelValue': [value: InterfaceConnectionDraft | null]
  /** «Применить конфигурацию соседа»: порту этой строки — назначение и/или режим соседа (kinds — что расходится). */
  'apply-peer-config': [peer: PeerConfigTarget, kinds: ConfigDiffKind[]]
  /** «Применить текущую конфигурацию»: соседу — назначение и/или режим порта этой строки. */
  'apply-config-to-peer': [peer: PeerConfigTarget, kinds: ConfigDiffKind[]]
}>()

const catalogs = useCatalogsStore()

const selfValue = computed(() => props.deviceId ?? SELF_DEVICE)
const selfSelected = computed(() => !!props.selfPorts && props.modelValue?.peer_device_id === selfValue.value)

// Устройства-соседи — у сервера: поиск по имени и серийному номеру со страницей в DEVICE_OPTIONS_PAGE_SIZE записей.
// Список запрашивается при открытии выпадающего списка и при вводе (с паузой), а не при показе блока: у большинства
// портов соседа не меняют. В каждый запрос уходит include с текущим соседом, чтобы его подпись не пропала из списка
// при поиске, и exclude с редактируемым устройством. Ответ устаревшего запроса отбрасывается (deviceSeq).
const DEVICE_SEARCH_DEBOUNCE_MS = 250
const deviceResults = ref<DeviceOption[]>([])
const deviceTotal = ref(0)
const deviceQuery = ref('')
const devicesLoading = ref(false)
const devicesError = ref<string | null>(null)
let deviceSeq = 0
let deviceTimer: ReturnType<typeof setTimeout> | undefined

async function loadDevices(query: string) {
  const seq = ++deviceSeq
  devicesError.value = null
  devicesLoading.value = true
  try {
    const selected = props.modelValue?.peer_device_id
    const page = await fetchDeviceOptionsPage({
      q: query,
      include: selected && !selfSelected.value ? [selected] : [],
      exclude: props.deviceId ? [props.deviceId] : [],
      limit: DEVICE_OPTIONS_PAGE_SIZE,
    })
    if (seq !== deviceSeq) return
    deviceResults.value = page.items
    deviceTotal.value = page.total
  } catch (err) {
    if (seq !== deviceSeq) return
    deviceResults.value = []
    deviceTotal.value = 0
    devicesError.value = err instanceof Error ? err.message : 'неизвестная ошибка'
  } finally {
    if (seq === deviceSeq) devicesLoading.value = false
  }
}

function onDeviceSearch(query: string) {
  deviceQuery.value = query
  clearTimeout(deviceTimer)
  // Открытие списка (пустой запрос) — сразу, ввод — после паузы, чтобы не слать запрос на каждую букву.
  if (!query) void loadDevices('')
  else deviceTimer = setTimeout(() => void loadDevices(query), DEVICE_SEARCH_DEBOUNCE_MS)
}
onBeforeUnmount(() => clearTimeout(deviceTimer))

// Подпись выбранного устройства есть в черновике (peer_device_name). Если её нет (черновик собран без неё), один раз
// спрашиваем сервер: include вернёт это устройство при любом поиске.
watch(
  () => [props.modelValue?.peer_device_id ?? '', props.modelValue?.peer_device_name ?? '', selfSelected.value] as const,
  ([id, name, self]) => {
    if (id && !name && !self) void loadDevices('')
  },
  { immediate: true },
)

const ownLabel = computed(() => (props.deviceId ? (props.deviceLabel ? `${props.deviceLabel} (это устройство)` : 'Это устройство') : 'Это устройство (новое)'))

const deviceOptions = computed(() => {
  const options = deviceResults.value.map((d) => ({ value: d.id, label: d.label }))
  const draft = props.modelValue
  // Выбранный сосед может не попасть в найденное (поиск по другому тексту) — подпись держим в списке сами.
  if (draft?.peer_device_id && !selfSelected.value && !options.some((o) => o.value === draft.peer_device_id) && draft.peer_device_name) {
    options.unshift({ value: draft.peer_device_id, label: draft.peer_device_name })
  }
  if (!props.selfPorts) return options
  // Пункт «это устройство» не приходит с сервера: он есть всегда, но при поиске показывается, только если подходит.
  const needle = deviceQuery.value.trim().toLowerCase()
  if (needle && !ownLabel.value.toLowerCase().includes(needle)) return options
  return [{ value: selfValue.value, label: ownLabel.value }, ...options]
})
const deviceHint = computed(() =>
  deviceTotal.value > deviceResults.value.length ? `Показаны первые ${deviceResults.value.length} из ${deviceTotal.value} — уточните поиск` : '',
)

// Порты выбранного устройства-соседа с сервера: свободные плюс запрошенные явно (текущий сосед этой строки и
// порты, которые эта форма освобождает, — на сервере они ещё заняты). Обновляется при смене устройства и когда
// форма освобождает новые порты; ответ устаревшего запроса отбрасывается (loadSeq).
const peerPorts = ref<FreeInterface[]>([])
const peersLoading = ref(false)
const peersError = ref<string | null>(null)
let loadSeq = 0

async function loadPeerPorts() {
  const draft = props.modelValue
  const seq = ++loadSeq
  peersError.value = null
  if (!draft?.peer_device_id || selfSelected.value) {
    peerPorts.value = []
    peersLoading.value = false
    return
  }
  peersLoading.value = true
  try {
    const include = [...new Set([draft.peer_interface_id, ...props.freedPeerIds].filter(Boolean))]
    const ports = await fetchAllFreeInterfaces(draft.peer_device_id, include)
    if (seq === loadSeq) peerPorts.value = ports
  } catch (err) {
    if (seq !== loadSeq) return
    peerPorts.value = []
    peersError.value = err instanceof Error ? err.message : 'неизвестная ошибка'
  } finally {
    if (seq === loadSeq) peersLoading.value = false
  }
}
watch(() => [props.modelValue?.peer_device_id ?? '', selfSelected.value, [...props.freedPeerIds].sort().join(','), props.peersVersion], loadPeerPorts, { immediate: true })

const peerInterfaces = computed(() => {
  const draft = props.modelValue
  if (!draft?.peer_device_id || selfSelected.value) return []
  return peerPorts.value.filter((p) => p.id === draft.peer_interface_id || ((!p.occupied || props.freedPeerIds.has(p.id)) && !props.takenPeerIds.has(p.id)))
})
const portOptions = computed(() => (selfSelected.value ? (props.selfPorts ?? []).map((c) => ({ value: c.value, label: c.label })) : peerInterfaces.value.map((p) => ({ value: p.id, label: p.name }))))
const typeOptions = computed(() => (catalogs.items['connection-types'] ?? []).map((t) => ({ value: t.id, label: t.name })))

const noFreePortsHint = computed(() => {
  if (!props.modelValue?.peer_device_id || peersLoading.value || peersError.value || portOptions.value.length) return ''
  return selfSelected.value
    ? 'В этом устройстве нет свободных портов, кроме редактируемого: добавьте ещё один порт или освободите существующий.'
    : 'У выбранного устройства нет свободных сохранённых портов: все заняты активными подключениями или ещё не созданы.'
})

// Сосед выбранного подключения и его конфигурация. Порт этого же устройства сверяем по текущим значениям
// строки формы, а не по сохранённым данным; порт другого устройства — по данным сервера.
const peerTarget = computed<PeerConfigTarget | null>(() => {
  const draft = props.modelValue
  const ref = draft ? peerRef(draft) : ''
  if (!draft || !ref) return null
  if (selfSelected.value) {
    const candidate = props.selfPorts?.find((c) => c.value === ref)
    return candidate ? { ref, label: `«${candidate.label}» (это устройство)`, config: candidate.config, interfaceId: candidate.interfaceId, rowKey: candidate.rowKey, isSelf: true } : null
  }
  const port = peerPorts.value.find((p) => p.id === draft.peer_interface_id)
  return port ? { ref, label: `«${port.name}» (${draft.peer_device_name ?? 'другое устройство'})`, config: port, interfaceId: port.id, isSelf: false } : null
})
const configDiffs = computed(() => (peerTarget.value ? connectionConfigDiffs(props.config, peerTarget.value.config) : []))
const configDiffKinds = computed(() => (peerTarget.value ? connectionConfigDiffKinds(props.config, peerTarget.value.config) : []))

function patch(change: Partial<InterfaceConnectionDraft>) {
  if (!props.modelValue) return
  const next = { ...props.modelValue, ...change }
  // Необязательные поля без значения не храним: черновик остаётся чистым для сравнения со снимком.
  if (next.peer_row_key === undefined) delete next.peer_row_key
  if (next.peer_interface_name === undefined) delete next.peer_interface_name
  if (next.peer_device_name === undefined) delete next.peer_device_name
  emit('update:modelValue', next)
}
// Смена устройства-соседа сбрасывает порт: иначе в черновике остался бы порт другого устройства.
function onPeerDeviceChange(deviceId: string) {
  const name = deviceId && deviceId !== selfValue.value ? deviceResults.value.find((d) => d.id === deviceId)?.label : undefined
  patch({ peer_device_id: deviceId, peer_device_name: name, peer_interface_id: '', peer_row_key: undefined, peer_interface_name: undefined })
}
// Несохранённая строка этого устройства выбирается по ключу, сохранённый порт — по id.
function onPeerPortChange(value: string) {
  const candidate = selfSelected.value ? props.selfPorts?.find((c) => c.value === value) : undefined
  if (candidate?.rowKey) patch({ peer_interface_id: '', peer_row_key: candidate.rowKey, peer_interface_name: undefined })
  else patch({ peer_interface_id: value, peer_row_key: undefined, peer_interface_name: selfSelected.value ? undefined : peerPorts.value.find((p) => p.id === value)?.name })
}
</script>

<template>
  <div class="connection-block">
    <div class="connection-head">
      <b>Подключение</b>
      <button v-if="!modelValue" type="button" class="btn btn-secondary connection-connect-btn" @click="emit('update:modelValue', emptyConnectionDraft())">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Подключить
      </button>
      <button v-else type="button" class="btn btn-secondary connection-disconnect-btn" @click="emit('update:modelValue', null)">
        <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        Отключить
      </button>
    </div>

    <div v-if="!modelValue" class="connection-empty">Порт не подключён</div>
    <template v-else>
      <div class="connection-grid">
        <label class="field connection-peer-device">
          <span>Устройство</span>
          <SearchableSelect
            :model-value="modelValue.peer_device_id"
            :options="deviceOptions"
            remote
            :loading="devicesLoading"
            :hint="deviceHint"
            placeholder="— выберите —"
            @search="onDeviceSearch"
            @update:model-value="onPeerDeviceChange"
          />
        </label>
        <label class="field connection-peer-port">
          <span>Порт *</span>
          <SearchableSelect :model-value="peerRef(modelValue)" :options="portOptions" :disabled="!modelValue.peer_device_id" placeholder="— выберите —" @update:model-value="onPeerPortChange" />
        </label>
        <label class="field connection-type">
          <span>Тип физической линии связи *</span>
          <SearchableSelect :model-value="modelValue.connection_type_id" :options="typeOptions" placeholder="— выберите —" @update:model-value="(v) => patch({ connection_type_id: v })" />
        </label>
        <label class="field connection-description">
          <span>Описание</span>
          <input type="text" :value="modelValue.description" maxlength="500" @input="patch({ description: ($event.target as HTMLInputElement).value })" />
        </label>
      </div>
      <small v-if="devicesError" class="connection-hint connection-error" role="alert">Не удалось загрузить устройства: {{ devicesError }}</small>
      <small v-if="peersLoading" class="connection-hint connection-loading">Загрузка портов устройства…</small>
      <small v-else-if="peersError" class="connection-hint connection-error" role="alert">Не удалось загрузить порты устройства: {{ peersError }}</small>
      <small v-else-if="noFreePortsHint" class="connection-hint">{{ noFreePortsHint }}</small>
      <div v-if="peerTarget && configDiffs.length" class="connection-diffs" role="alert">
        <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
        <div class="connection-diffs-body">
          <span>Конфигурация порта расходится с портом соседа — {{ configDiffs.join('; ') }}. Сохранить можно: расхождение будет отмечено на экране «Подключения».</span>
          <div class="connection-diffs-actions">
            <button type="button" class="btn btn-secondary" :disabled="applying" title="Этому порту — назначение, режим порта и «Все VLAN» соседа" @click="emit('apply-peer-config', peerTarget, configDiffKinds)">
              Применить конфигурацию соседа
            </button>
            <button type="button" class="btn btn-secondary" :disabled="applying" title="Соседу — назначение, режим порта и «Все VLAN» этого порта" @click="emit('apply-config-to-peer', peerTarget, configDiffKinds)">
              Применить текущую конфигурацию
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.connection-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.connection-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.connection-head b {
  font-size: 11.5px;
}
.connection-empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.connection-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--ink-muted);
  min-width: 0;
}
.field input[type='text'] {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.connection-hint {
  font-size: 11px;
  color: var(--ink-muted);
}
.connection-diffs {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink);
}
.connection-diffs-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.connection-diffs-actions .btn {
  padding: 5px 9px;
  font-size: 11.5px;
}
.connection-diffs-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.connection-diffs .conflict-icon {
  flex: none;
  color: var(--status-warn);
  width: 14px;
  height: 14px;
  margin-top: 1px;
}
@media (max-width: 640px) {
  .connection-grid {
    grid-template-columns: 1fr;
  }
}
</style>
