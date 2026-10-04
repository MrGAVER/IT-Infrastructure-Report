<script setup lang="ts">
// Проверка расхождения конфигурации у пары портов-соседей одного подключения (дашборд «Подключения»):
// роль (управление / передача данных), режим порта (access / trunk) и назначенные VLAN. Всё это
// хранится на самих портах; здесь пользователь видит обе стороны рядом, различающиеся значения
// подсвечены, и решает: одобрить расхождение как допустимое (например, порт управления сервера
// включён в порт коммутатора, настроенный на передачу данных), либо привести порты к одному виду.
// Роль выравнивается здесь же одним запросом. Режим порта — каскадом (composables/useVlanModeCascade.ts):
// режим могут задавать группы портов, и он должен совпасть у связанных портов, поэтому сервер считает всю
// область изменения, а окно показывает последствия до применения. VLAN правятся в окне портов
// устройства (событие manage-ports). Статус после любого действия пересчитывает сервер — клиент только
// подставляет его в список.
import { computed, onMounted, ref, watch } from 'vue'
import { setPortRole } from '../api/portConfig'
import { previewPortSync } from '../api/portSync'
import type { Connection, PortConfigFacet, PortSyncPlanItem } from '../api/types'
import PortSyncPlanModal from './PortSyncPlanModal.vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { useVlanModeCascade } from '../composables/useVlanModeCascade'
import type { VlanMode } from '../api/vlanModeCascade'
import { facetsLabel, formatVlans, modeLabel, roleLabel } from '../utils/portConfig'
import { changeLines, optionLine, targetPort } from '../utils/portSyncRules'
import VlanModeCascadeModal from './VlanModeCascadeModal.vue'

const props = defineProps<{ connection: Connection }>()
const emit = defineEmits<{
  close: []
  /** Открыть окно портов устройства, чтобы поправить режим порта и VLAN. */
  'manage-ports': [target: { interfaceId: string; deviceLabel: string }]
}>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const dashboard = useConnectionsDashboardStore()
const { notify } = useToast()

const busy = ref(false)
const errorMessage = ref<string | null>(null)

// Своя копия записи, а не строка из стора: список постраничный и с фильтрами, и после отзыва
// одобрения строка может исчезнуть со страницы (например, при фильтре «Одобренные»), хотя окно
// проверки ещё открыто. Копию обновляем ответом сервера.
const current = ref<Connection>(props.connection)
const isApproved = computed(() => current.value.port_config_status === 'approved')
const isMismatch = computed(() => current.value.port_config_status === 'mismatch')
const diff = computed(() => current.value.port_config_diff ?? [])
const differs = (facet: PortConfigFacet) => diff.value.includes(facet)
const needsVlanSetup = computed(() => differs('vlans'))

// Рекомендация по правилам согласования (страница «Правила согласования портов»): что сделает
// подходящее правило для этого подключения. Запрашивается у сервера при открытии окна и после
// каждого изменения статуса; сбой запроса рекомендацию просто не показывает — окно проверки от неё
// не зависит. Само согласование — через окно плана: изменения применяются только после подтверждения.
const recommendation = ref<PortSyncPlanItem | null>(null)
const planOpen = ref(false)
let recommendationSeq = 0

async function loadRecommendation() {
  const seq = ++recommendationSeq
  if (!isMismatch.value) {
    recommendation.value = null
    return
  }
  try {
    const plan = await previewPortSync({ connection_ids: [current.value.id] })
    const item = plan?.items?.find((i) => i.connection_id === current.value.id) ?? null
    if (seq === recommendationSeq) recommendation.value = item?.rule ? item : null
  } catch {
    if (seq === recommendationSeq) recommendation.value = null
  }
}

onMounted(loadRecommendation)
watch(() => current.value.port_config_status, loadRecommendation)

async function onPlanApplied() {
  await dashboard.refreshAfterChange()
  emit('close')
}

const recommendedPort = computed(() => (recommendation.value ? targetPort(recommendation.value) : null))

async function run(action: () => Promise<void>, fallbackError: string) {
  busy.value = true
  errorMessage.value = null
  try {
    await action()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : fallbackError
  } finally {
    busy.value = false
  }
}

function approve() {
  return run(async () => {
    await dashboard.approve([current.value.id])
    notify('Расхождение ролей портов одобрено', 'success')
    emit('close')
  }, 'Не удалось одобрить расхождение')
}

function revoke() {
  return run(async () => {
    current.value = await dashboard.revokeApproval(current.value.id)
    notify('Одобрение отозвано — расхождение снова требует проверки', 'info')
  }, 'Не удалось отозвать одобрение')
}

function managePorts(side: 'source' | 'destination') {
  const c = current.value
  emit('manage-ports', side === 'source'
    ? { interfaceId: c.source_interface_id, deviceLabel: c.source_device_name }
    : { interfaceId: c.destination_interface_id, deviceLabel: c.destination_device_name })
}

/** keepSource=true — порт назначения получает роль порта-источника, и наоборот. */
function align(keepSource: boolean) {
  const c = current.value
  const role = keepSource ? c.source_port_role : c.destination_port_role
  const targetInterfaceId = keepSource ? c.destination_interface_id : c.source_interface_id
  if (!role) return Promise.resolve()
  return run(async () => {
    catalogs.replaceInterface(await setPortRole(targetInterfaceId, role))
    await dashboard.refreshAfterChange()
    notify('Роль порта обновлена — роли портов подключения совпадают', 'success')
    emit('close')
  }, 'Не удалось изменить роль порта')
}

// Дашборд — не форма устройства: edited = null, изменения всех портов записываются сразу. После
// применения таблица и общий кэш перечитываются (статус сверки пересчитывает сервер), окно закрывается.
const {
  pending: cascadePending,
  applying: cascadeApplying,
  start: cascadeStart,
  confirm: cascadeConfirm,
  cancel: cascadeCancel,
} = useVlanModeCascade({
  edited: () => null,
  async onFinished() {
    await dashboard.refreshAfterChange()
    emit('close')
  },
})

/** keepSource=true — порт назначения получает режим порта-источника, и наоборот. Сервер сам расширит
 * область: группы портов, которые задают режим, и порты, связанные с изменяемыми. */
function alignMode(keepSource: boolean) {
  const c = current.value
  const mode: VlanMode | null = keepSource ? c.source_vlan_mode : c.destination_vlan_mode
  if (!mode) return Promise.resolve()
  const targetId = keepSource ? c.destination_interface_id : c.source_interface_id
  const label = keepSource ? `«${c.destination_interface_name}» (${c.destination_device_name})` : `«${c.source_interface_name}» (${c.source_device_name})`
  return run(async () => {
    await cascadeStart(targetId, mode, label)
  }, 'Не удалось изменить режим порта')
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" aria-label="Конфигурация портов подключения">
      <div class="modal-head">
        <h2>Конфигурация портов подключения</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <div class="pair">
        <div class="side">
          <div class="side-title">Источник</div>
          <div class="devname">{{ current.source_device_name }}</div>
          <div class="portname mono">{{ current.source_interface_name }}</div>
          <div class="role cfg" :class="{ diff: differs('role') }" data-side="source">{{ roleLabel(current.source_port_role) }}</div>
          <div class="cfg" :class="{ diff: differs('mode') }" data-mode-side="source">Режим: {{ modeLabel(current.source_vlan_mode) }}</div>
          <div class="cfg" :class="{ diff: differs('vlans') }" data-vlans-side="source">VLAN: {{ formatVlans(current.source_vlans) }}</div>
        </div>
        <div class="link-icon"><svg class="icon"><use href="/icons.svg#i-network" /></svg></div>
        <div class="side">
          <div class="side-title">Назначение</div>
          <div class="devname">{{ current.destination_device_name }}</div>
          <div class="portname mono">{{ current.destination_interface_name }}</div>
          <div class="role cfg" :class="{ diff: differs('role') }" data-side="destination">{{ roleLabel(current.destination_port_role) }}</div>
          <div class="cfg" :class="{ diff: differs('mode') }" data-mode-side="destination">Режим: {{ modeLabel(current.destination_vlan_mode) }}</div>
          <div class="cfg" :class="{ diff: differs('vlans') }" data-vlans-side="destination">VLAN: {{ formatVlans(current.destination_vlans) }}</div>
        </div>
      </div>

      <p v-if="isMismatch" class="status warn">⚠ Конфигурации портов различаются ({{ facetsLabel(diff) }}), решение не принято.</p>
      <p v-else-if="isApproved" class="status approved">
        ✓ Расхождение ({{ facetsLabel(diff) }}) одобрено — оно считается допустимым, пока роль, режим и VLAN портов не изменятся.
      </p>
      <p v-else class="status">Конфигурации портов совпадают.</p>

      <div v-if="recommendation" class="recommendation" :class="recommendation.outcome" data-recommendation>
        <div class="recommendation-title">По правилам согласования: «{{ recommendation.rule!.name }}»</div>
        <template v-if="recommendation.outcome === 'auto'">
          <div v-if="recommendedPort">Порту «{{ recommendedPort.name }}» ({{ recommendedPort.device_name }}) будет применено:</div>
          <ul class="recommendation-lines">
            <li v-for="line in changeLines(recommendation.changes)" :key="line">{{ line }}</li>
          </ul>
          <p v-for="warning in recommendation.warnings" :key="warning" class="recommendation-note" data-recommendation-warning>⚠ {{ warning }}</p>
          <button type="button" class="btn btn-secondary" data-action="plan" :disabled="busy" @click="planOpen = true">Согласовать по правилу…</button>
        </template>
        <template v-else-if="recommendation.outcome === 'blocked'">
          <p class="recommendation-note bad" data-recommendation-reason>{{ recommendation.reason }}</p>
        </template>
        <template v-else-if="recommendation.outcome === 'manual'">
          <p class="recommendation-note">Какой порт менять, решает человек — выберите действие ниже.</p>
          <ul v-if="recommendation.options.length" class="recommendation-lines">
            <li v-for="option in recommendation.options" :key="option.target">Можно применить к {{ optionLine(option, recommendation) }}</li>
          </ul>
        </template>
        <p v-else class="recommendation-note">{{ recommendation.rule!.action === 'ignore' ? 'Правило исключает эту пару из согласования.' : '' }}</p>
      </div>

      <div class="actions">
        <button v-if="isMismatch" type="button" class="btn btn-primary" data-action="approve" :disabled="busy" @click="approve">
          Одобрить расхождение
        </button>
        <button v-if="isApproved" type="button" class="btn btn-secondary" data-action="revoke" :disabled="busy" @click="revoke">
          Отозвать одобрение
        </button>
        <template v-if="isMismatch || isApproved">
          <template v-if="differs('role')">
            <button type="button" class="btn btn-secondary" data-action="keep-source" :disabled="busy" @click="align(true)">
              Порту «{{ current.destination_interface_name }}» задать роль как у «{{ current.source_interface_name }}»
            </button>
            <button type="button" class="btn btn-secondary" data-action="keep-destination" :disabled="busy" @click="align(false)">
              Порту «{{ current.source_interface_name }}» задать роль как у «{{ current.destination_interface_name }}»
            </button>
          </template>
          <template v-if="differs('mode')">
            <button type="button" class="btn btn-secondary" data-action="mode-to-destination" :disabled="busy" @click="alignMode(true)">
              Порту «{{ current.destination_interface_name }}» задать режим как у «{{ current.source_interface_name }}» ({{ modeLabel(current.source_vlan_mode) }})
            </button>
            <button type="button" class="btn btn-secondary" data-action="mode-to-source" :disabled="busy" @click="alignMode(false)">
              Порту «{{ current.source_interface_name }}» задать режим как у «{{ current.destination_interface_name }}» ({{ modeLabel(current.destination_vlan_mode) }})
            </button>
          </template>
          <template v-if="needsVlanSetup">
            <button type="button" class="btn btn-secondary" data-action="manage-source" :disabled="busy" @click="managePorts('source')">
              Настроить VLAN: «{{ current.source_interface_name }}» ({{ current.source_device_name }})
            </button>
            <button type="button" class="btn btn-secondary" data-action="manage-destination" :disabled="busy" @click="managePorts('destination')">
              Настроить VLAN: «{{ current.destination_interface_name }}» ({{ current.destination_device_name }})
            </button>
          </template>
        </template>
      </div>

      <p v-if="differs('mode')" class="hint">
        Режим порта может задаваться группой портов, и он должен совпасть у связанных портов — при необходимости режим сменится у всей группы и у связанных
        с ней портов. Перед применением покажем список всех последствий.
      </p>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" @click="$emit('close')">Закрыть</button>
      </div>
    </div>
    <PortSyncPlanModal
      v-if="planOpen"
      :scope="{ connection_ids: [current.id] }"
      title="Согласование портов по правилу"
      @close="planOpen = false"
      @applied="onPlanApplied"
    />
  </div>

  <VlanModeCascadeModal
    v-if="cascadePending"
    :plan="cascadePending.plan"
    :applying="cascadeApplying"
    :port-label="cascadePending.portLabel"
    @confirm="cascadeConfirm"
    @cancel="cascadeCancel"
  />
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 620px;
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
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.pair {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 10px;
  align-items: stretch;
  margin-bottom: 14px;
}
.side {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.side-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.devname {
  font-weight: 600;
  font-size: 13px;
}
.portname {
  color: var(--ink-muted);
  font-size: 11.5px;
}
.role {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink);
}
.cfg {
  font-size: 12.5px;
  color: var(--ink);
  border-radius: var(--r-s);
  padding: 1px 4px;
  margin: 0 -4px;
}
.cfg.diff {
  background: var(--status-warn-soft);
  font-weight: 600;
}
.link-icon {
  display: flex;
  align-items: center;
  color: var(--ink-muted);
}
.link-icon .icon {
  width: 18px;
  height: 18px;
}
.status {
  margin: 0 0 14px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.status.warn {
  color: var(--ink);
  background: var(--status-warn-soft);
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  padding: 8px 10px;
}
.status.approved {
  color: var(--status-ok, var(--ink));
}
.recommendation {
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  border-radius: var(--r-m);
  padding: 10px 12px;
  margin: 0 0 14px;
  font-size: 12.5px;
}
.recommendation.blocked {
  border-color: var(--status-warn);
  background: var(--status-warn-soft);
}
.recommendation-title {
  font-weight: 700;
  margin-bottom: 4px;
}
.recommendation-lines {
  margin: 4px 0 8px;
  padding-left: 18px;
}
.recommendation-note {
  margin: 4px 0 8px;
}
.recommendation-note.bad {
  font-weight: 600;
}
.actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.hint {
  margin: 10px 0 0;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .pair {
    grid-template-columns: 1fr;
  }
  .link-icon {
    justify-content: center;
    transform: rotate(90deg);
  }
}
</style>
