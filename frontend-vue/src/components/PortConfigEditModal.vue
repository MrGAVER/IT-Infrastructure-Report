<script setup lang="ts">
// Правка конфигурации одного порта прямо с дашборда «Подключения»: роль (управление / передача данных),
// режим (access / trunk) и набор VLAN. Раньше режим и VLAN правились только в окне всех портов устройства,
// а роль — только «как у соседа».
//
// Как это записывается:
//  * режим меняется — каскадом (composables/useVlanModeCascade.ts): режим может задаваться группой портов и
//    должен совпасть у связанных портов, поэтому сервер считает всю область изменения, а окно показывает
//    последствия до применения. Роль и набор VLAN уходят В ТОМ ЖЕ запросе (поле `port`) и записываются
//    одной транзакцией с каскадом: либо записано всё, либо ничего. Ошибку в роли или VLAN сервер показывает уже
//    при предпросмотре, до подтверждения каскада;
//  * режим не меняется — роль и набор VLAN одним атомарным запросом PUT /interfaces/{id}/port-config
//    (api/portConfig.ts). Так же — если при предпросмотре оказалось, что режим уже целевой (его успели сменить).
// Порт в группе, которая задаёт режим и VLAN, по VLAN не правится (группа — источник истины): режим при этом
// сменить можно — он поменяется у всей группы, как и в окне проверки расхождения.
//
// Статус сверки и таблицу после правки пересчитывает сервер — окно только просит дашборд перечитать список.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { loadDeviceInterfaceGroups } from '../api/deviceInterfaces'
import { setPortConfig } from '../api/portConfig'
import { computePortVlanOptions, loadAssignedDeviceVlanIds, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Connection, Device, DeviceInterface, InterfaceGroupDraft, InterfaceVlansEntry, PortRole, VLANDefinition, VlanMode } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useVLANsStore } from '../stores/vlans'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { useVlanModeCascade, type CascadeOutcome } from '../composables/useVlanModeCascade'
import type { CascadePortRequest } from '../api/vlanModeCascade'
import { PORT_ROLE_LABELS, facetsLabel, formatVlans, portRoleOf } from '../utils/portConfig'
import {
  adaptVlanIdsToMode,
  buildPortConfigPatch,
  cloneDraft,
  differencesFromNeighbor,
  isDirty,
  numbersOf,
  validateDraft,
  vlanIdsForNumbers,
  type PortDraft,
} from '../utils/portEdit'
import VlanModeCascadeModal from './VlanModeCascadeModal.vue'

const props = defineProps<{ connection: Connection; side: 'source' | 'destination' }>()
const emit = defineEmits<{
  close: []
  /** Правка сохранена (или менять было нечего): таблица уже перечитана, окно можно закрывать. */
  saved: []
  /** Открыть окно всех портов устройства — например, чтобы изменить группу, которая задаёт VLAN порта. */
  'manage-ports': [target: { interfaceId: string; deviceLabel: string }]
}>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => {
  if (!saving.value && !cascadeApplying.value) emit('close')
})

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const dashboard = useConnectionsDashboardStore()
const { notify } = useToast()

const own = computed(() => {
  const c = props.connection
  return props.side === 'source'
    ? { interfaceId: c.source_interface_id, name: c.source_interface_name, deviceLabel: c.source_device_name }
    : { interfaceId: c.destination_interface_id, name: c.destination_interface_name, deviceLabel: c.destination_device_name }
})
// Сосед — только для сравнения: его конфигурация здесь не меняется.
const neighbor = computed(() => {
  const c = props.connection
  return props.side === 'source'
    ? {
        name: c.destination_interface_name,
        deviceLabel: c.destination_device_name,
        role: c.destination_port_role,
        mode: c.destination_vlan_mode,
        vlans: c.destination_vlans,
      }
    : { name: c.source_interface_name, deviceLabel: c.source_device_name, role: c.source_port_role, mode: c.source_vlan_mode, vlans: c.source_vlans }
})

const ROLES: PortRole[] = ['none', 'management', 'data', 'management_data']
const MODES: VlanMode[] = ['access', 'trunk']

const loading = ref(true)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const notice = ref<string | null>(null)

const vlanOptions = ref<VLANDefinition[]>([])
const group = ref<InterfaceGroupDraft | null>(null)
const initial = ref<PortDraft>({ role: 'none', mode: 'trunk', vlanIds: [], allVlans: false })
const draft = reactive<PortDraft>({ role: 'none', mode: 'trunk', vlanIds: [], allVlans: false })

// Группа, задающая режим и VLAN порта, — источник истины: набор VLAN порта здесь не правится.
const vlansLocked = computed(() => Boolean(group.value?.vlan_mode))
const modeChanged = computed(() => draft.mode !== initial.value.mode)
const dirty = computed(() => isDirty(initial.value, draft))
const draftVlanNumbers = computed(() => numbersOf(vlanOptions.value, draft.vlanIds))
const differences = computed(() => differencesFromNeighbor(draft, draftVlanNumbers.value, neighbor.value))

function setDraft(next: PortDraft) {
  draft.role = next.role
  draft.mode = next.mode
  draft.vlanIds = [...next.vlanIds]
  draft.allVlans = next.allVlans
}

/** Текущее состояние порта с сервера: роль, режим, VLAN и группа — не из строки таблицы, которая могла устареть. */
async function loadPort() {
  const id = own.value.interfaceId
  const iface = await api.get<DeviceInterface>(`/resources/interfaces/${id}`)
  // VLAN порта — запросом устройства: он учитывает признак «Все VLAN» (у такого порта связей в БД нет, набор — все VLAN
  // устройства), которого generic-список связей не знает.
  const [device, portVlans, groups] = await Promise.all([
    api.get<Device>(`/resources/devices/${iface.physical_device_id}`),
    api.get<{ items: InterfaceVlansEntry[] }>(`/devices/${iface.physical_device_id}/interface-vlans`),
    iface.group_id ? loadDeviceInterfaceGroups(iface.physical_device_id) : Promise.resolve([] as InterfaceGroupDraft[]),
  ])
  const [typeVlanIds, assignedVlanIds] = await Promise.all([loadDeviceTypeVlanIds(device.device_type_id), loadAssignedDeviceVlanIds(iface.physical_device_id)])
  vlanOptions.value = computePortVlanOptions(vlansStore.allDefinitions, typeVlanIds, assignedVlanIds)
  group.value = groups.find((g) => g.id === iface.group_id) ?? null
  const portEntry = portVlans.items.find((item) => item.interface_id === id)
  const mode = (iface.vlan_mode as VlanMode) || 'trunk'
  initial.value = {
    role: portRoleOf(iface),
    mode,
    vlanIds: [...new Set(portEntry?.vlan_ids ?? [])],
    allVlans: mode === 'trunk' && portEntry?.all_vlans === true,
  }
  setDraft(initial.value)
}

onMounted(async () => {
  try {
    await Promise.all([catalogs.ensureLoaded(), vlansStore.ensureLoaded()])
    await loadPort()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить настройки порта'
  } finally {
    loading.value = false
  }
})

// В access остаётся один VLAN с наименьшим номером — как в форме устройства и в каскаде; у порта в группе
// набор не трогаем: его определит каскад по группе.
watch(
  () => draft.mode,
  (mode) => {
    if (loading.value || vlansLocked.value) return
    if (mode === 'access') draft.allVlans = false // «Все VLAN» только в trunk
    const adapted = adaptVlanIdsToMode(vlanOptions.value, draft.vlanIds, mode)
    if (adapted.length !== draft.vlanIds.length) {
      notice.value = 'В режиме access у порта один VLAN — оставлен VLAN с наименьшим номером.'
      draft.vlanIds = adapted
    }
  },
)

function toggleVlan(id: string, checked: boolean) {
  notice.value = null
  if (draft.mode === 'access') draft.vlanIds = checked ? [id] : []
  else draft.vlanIds = checked ? [...new Set([...draft.vlanIds, id])] : draft.vlanIds.filter((v) => v !== id)
  draft.allVlans = false // ручной выбор снимает «Все VLAN», даже если выбраны все
}

function selectAllVlans() {
  notice.value = null
  draft.vlanIds = vlanOptions.value.map((o) => o.id)
  draft.allVlans = true // сохраняемый признак, а не просто полный набор
}

function clearVlans() {
  notice.value = null
  draft.vlanIds = []
  draft.allVlans = false
}

/** Роль, режим и VLAN как у порта на другом конце подключения. VLAN сопоставляются по НОМЕРУ — как и при
 * сверке; номера, которых нет у устройства порта, не назначаются. */
function copyFromNeighbor() {
  const n = neighbor.value
  notice.value = null
  if (n.role) draft.role = n.role
  if (n.mode) draft.mode = n.mode
  if (!vlansLocked.value) {
    const { ids, missing } = vlanIdsForNumbers(vlanOptions.value, n.vlans)
    draft.vlanIds = adaptVlanIdsToMode(vlanOptions.value, ids, draft.mode)
    draft.allVlans = false // набор сопоставлен по номерам — это выбор вручную, не «Все VLAN»
    if (missing.length) notice.value = `У устройства порта нет VLAN ${formatVlans(missing)} — они не назначены.`
  }
}

// --- запись ------------------------------------------------------------------------------------

/** Роль и набор VLAN обычным запросом (режим не менялся, либо уже был целевым). Ошибку не пробрасывает, а показывает
 * в окне и перечитывает состояние порта — введённое пользователем не теряется, можно повторить. `resendVlans` —
 * набор отправляется целиком, даже если он совпал с исходным (режим порта менялся другим способом). */
async function applyRoleAndVlans(resendVlans: boolean) {
  const patch = buildPortConfigPatch(initial.value, draft, { modeChanged: resendVlans, vlansLocked: vlansLocked.value })
  try {
    if (patch) {
      catalogs.replaceInterface(await setPortConfig(own.value.interfaceId, patch))
      notify('Конфигурация порта обновлена', 'success')
    } else if (!resendVlans) {
      notify('Изменений нет', 'info')
    }
    await dashboard.refreshAfterChange()
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить роль и VLAN порта'
    await refreshAfterFailure()
  }
}

/** Роль и VLAN для записи вместе с каскадом: то же, что `buildPortConfigPatch`, без режима (его задаёт каскад). */
function cascadePortRequest(): CascadePortRequest | null {
  const patch = buildPortConfigPatch(initial.value, draft, { modeChanged: true, vlansLocked: vlansLocked.value })
  if (!patch) return null
  const request: CascadePortRequest = {}
  if (patch.role !== undefined) request.role = patch.role
  if (patch.vlan_ids !== undefined) request.vlan_ids = patch.vlan_ids
  if (patch.all_vlans !== undefined) request.all_vlans = patch.all_vlans
  return request
}

async function refreshAfterFailure() {
  try {
    const wanted = cloneDraft(draft)
    await loadPort()
    setDraft(wanted) // введённое пользователем не теряем — сверка с исходным пересчитается с новым состоянием порта
    await dashboard.refreshAfterChange()
  } catch {
    /* состояние порта не обновилось — ошибка выше уже показана, окно остаётся как есть */
  }
}

let cascadePort: CascadePortRequest | null = null
const {
  pending: cascadePending,
  applying: cascadeApplying,
  start: cascadeStart,
  confirm: cascadeConfirm,
  cancel: cascadeCancel,
} = useVlanModeCascade({
  edited: () => null,
  port: () => cascadePort,
  async onFinished(outcome: CascadeOutcome) {
    if (outcome === 'unchanged') {
      // Режим уже целевой — каскад ничего не применял, роль и VLAN идут обычной правкой.
      await applyRoleAndVlans(true)
      return
    }
    // Режим, роль и VLAN записаны одной транзакцией каскада.
    if (cascadePort) notify('Конфигурация порта обновлена', 'success')
    await dashboard.refreshAfterChange()
    emit('saved')
  },
})

async function save() {
  errorMessage.value = validateDraft(draft, { vlansLocked: vlansLocked.value })
  if (errorMessage.value) return
  if (!dirty.value) {
    emit('close')
    return
  }
  saving.value = true
  try {
    if (modeChanged.value) {
      // Предпросмотр (вместе с проверкой роли и VLAN) и подтверждение — в окне каскада; запись — одним запросом.
      cascadePort = cascadePortRequest()
      await cascadeStart(own.value.interfaceId, draft.mode, `«${own.value.name}» (${own.value.deviceLabel})`)
    } else {
      await applyRoleAndVlans(false)
    }
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить настройки порта'
  } finally {
    saving.value = false
  }
}

function manageGroup() {
  emit('manage-ports', { interfaceId: own.value.interfaceId, deviceLabel: own.value.deviceLabel })
}

const vlanLabel = (o: VLANDefinition) => `VLAN ${o.vlan_id}${o.name ? ` · ${o.name}` : ''}${o.domain_name ? ` (${o.domain_name})` : ''}`
</script>

<template>
  <!-- Teleport в body: окно открывается поверх таблицы и окна проверки расхождения (оба — оверлеи), как и
       DevicePortsModal.vue; без него получился бы вложенный position:fixed оверлей внутри оверлея. -->
  <Teleport to="body">
    <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="Конфигурация порта" data-modal="port-config-edit">
        <div class="modal-head">
          <h2>Порт «{{ own.name }}» · {{ own.deviceLabel }}</h2>
          <button type="button" class="icon-btn" aria-label="Закрыть" :disabled="saving" @click="$emit('close')">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
          </button>
        </div>

        <div v-if="errorMessage" class="form-error" role="alert" data-error>
          <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
          <span>{{ errorMessage }}</span>
        </div>

        <p v-if="loading" class="loading" data-loading>Загрузка настроек порта…</p>

        <template v-else>
          <p class="neighbor" data-neighbor>
            Соседний порт: «{{ neighbor.name }}» ({{ neighbor.deviceLabel }}) — {{ neighbor.role ? PORT_ROLE_LABELS[neighbor.role] : 'роль не задана' }}, режим
            {{ neighbor.mode ?? '—' }}, VLAN {{ formatVlans(neighbor.vlans) }}
            <button type="button" class="link-btn" data-action="copy-neighbor" :disabled="saving" @click="copyFromNeighbor">Задать как у соседа</button>
          </p>

          <label class="field">
            <span>Роль порта</span>
            <select v-model="draft.role" data-field="role" :disabled="saving">
              <option v-for="role in ROLES" :key="role" :value="role">{{ PORT_ROLE_LABELS[role] }}</option>
            </select>
          </label>

          <div class="field">
            <span>Режим порта</span>
            <div class="chip-group" role="group" aria-label="Режим порта">
              <button
                v-for="mode in MODES"
                :key="mode"
                type="button"
                :class="{ on: draft.mode === mode }"
                :data-field="`mode-${mode}`"
                :aria-pressed="draft.mode === mode"
                :disabled="saving"
                @click="draft.mode = mode"
              >
                {{ mode }}
              </button>
            </div>
            <p v-if="modeChanged" class="hint" data-hint="cascade">
              Режим меняется каскадом: если порт входит в группу, задающую режим, или связан с портами, у которых режим другой, он сменится и у них. Перед
              применением покажем все последствия; роль и VLAN сохранятся в той же операции — всё или ничего.
            </p>
          </div>

          <div class="field">
            <span>VLAN порта</span>
            <p v-if="vlansLocked" class="hint locked" data-hint="group-locked">
              Режим и VLAN этого порта задаёт группа «{{ group?.name }}» — набор VLAN здесь не меняется. Режим сменить можно (он поменяется у всей группы), VLAN
              группы правятся в окне портов устройства.
              <button type="button" class="link-btn" data-action="manage-group" @click="manageGroup">Открыть порты устройства</button>
            </p>
            <p v-else-if="!vlanOptions.length" class="hint" data-hint="no-vlans">
              У устройства нет доступных VLAN — добавьте их в блоке «VLAN устройства» формы устройства.
            </p>
            <template v-else>
              <div class="vlan-tools">
                <button type="button" class="link-btn" data-action="select-all" :disabled="saving || draft.mode === 'access'" @click="selectAllVlans">
                  Все VLAN
                </button>
                <button type="button" class="link-btn" data-action="clear" :disabled="saving || !draft.vlanIds.length" @click="clearVlans">Снять все</button>
                <span class="count" data-count
                  >Выбрано: {{ draft.vlanIds.length }} из {{ vlanOptions.length }}<template v-if="draft.allVlans"> · признак «Все VLAN»</template></span
                >
              </div>
              <!-- key по режиму: при смене checkbox ↔ radio список пересоздаётся. Иначе у живых input с общим name
                   браузер сбрасывает «выбранность» у остальных радиокнопок, и на экране не отмечено ничего, хотя
                   в черновике VLAN остался. -->
              <ul :key="draft.mode" class="vlan-list" data-vlan-list>
                <li v-for="o in vlanOptions" :key="o.id">
                  <label>
                    <input
                      :type="draft.mode === 'access' ? 'radio' : 'checkbox'"
                      name="port-vlan"
                      :data-vlan="o.id"
                      :checked="draft.vlanIds.includes(o.id)"
                      :disabled="saving"
                      @change="toggleVlan(o.id, ($event.target as HTMLInputElement).checked)"
                    />
                    <span>{{ vlanLabel(o) }}</span>
                  </label>
                </li>
              </ul>
              <p v-if="draft.mode === 'access'" class="hint">В режиме access у порта не более одного VLAN.</p>
            </template>
            <p v-if="notice" class="hint warn" data-notice>{{ notice }}</p>
          </div>

          <p class="compare" :class="{ ok: !differences.length }" data-compare>
            <template v-if="!differences.length">✓ После сохранения конфигурация совпадёт с соседним портом.</template>
            <template v-else>⚠ От соседнего порта будет отличаться: {{ facetsLabel(differences) }}. Расхождение можно одобрить на дашборде.</template>
          </p>
        </template>

        <div class="modal-foot">
          <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
          <button type="button" class="btn btn-primary" data-action="save" :disabled="loading || saving || !dirty" @click="save">
            {{ modeChanged ? 'Далее — проверить последствия' : 'Сохранить' }}
          </button>
        </div>
      </div>

      <VlanModeCascadeModal
        v-if="cascadePending"
        :plan="cascadePending.plan"
        :applying="cascadeApplying"
        :port-label="cascadePending.portLabel"
        @confirm="cascadeConfirm"
        @cancel="cascadeCancel"
      />
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 70;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 560px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--crit-ink);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.loading {
  color: var(--ink-muted);
  font-size: 13px;
  text-align: center;
  padding: 24px 0;
}
.neighbor {
  margin: 0 0 14px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--ink-muted);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.field > span {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.chip-group {
  display: inline-flex;
  align-self: flex-start;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
}
.chip-group button {
  border: none;
  background: var(--surface);
  padding: 7px 16px;
  font-size: 12.5px;
  color: var(--ink-muted);
  font-weight: 500;
  border-right: 1px solid var(--border);
}
.chip-group button:last-child {
  border-right: none;
}
.chip-group button.on {
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-weight: 700;
}
.vlan-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.count {
  margin-left: auto;
  color: var(--ink-muted);
}
.vlan-list {
  list-style: none;
  margin: 0;
  padding: 6px 8px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
}
.vlan-list label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 12.5px;
  cursor: pointer;
}
.link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--brand);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.link-btn:disabled {
  color: var(--ink-muted);
  cursor: default;
}
.hint {
  margin: 0;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.hint.warn,
.hint.locked {
  color: var(--ink);
  background: var(--status-warn-soft);
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  padding: 7px 9px;
}
.compare {
  margin: 0;
  padding: 8px 10px;
  font-size: 12.5px;
  color: var(--ink);
  background: var(--status-warn-soft);
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
}
.compare.ok {
  color: var(--status-ok, var(--ink));
  background: transparent;
  border-color: var(--border);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
