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
import type { Connection, PortRole, VLANDefinition, VlanMode } from '../api/types'
import { usePortConfigEdit } from '../composables/usePortConfigEdit'
import { PORT_ROLE_LABELS, facetsLabel, formatVlans } from '../utils/portConfig'
import BaseModal from './BaseModal.vue'
import VlanModeCascadeModal from './VlanModeCascadeModal.vue'

const props = defineProps<{ connection: Connection; side: 'source' | 'destination' }>()
const emit = defineEmits<{
  close: []
  /** Правка сохранена (или менять было нечего): таблица уже перечитана, окно можно закрывать. */
  saved: []
  /** Открыть окно всех портов устройства — например, чтобы изменить группу, которая задаёт VLAN порта. */
  'manage-ports': [target: { interfaceId: string; deviceLabel: string }]
}>()

// Состояние, загрузка и запись правки — composables/usePortConfigEdit.ts.
const {
  own,
  neighbor,
  loading,
  saving,
  errorMessage,
  notice,
  vlanOptions,
  group,
  draft,
  vlansLocked,
  modeChanged,
  dirty,
  differences,
  toggleVlan,
  selectAllVlans,
  clearVlans,
  copyFromNeighbor,
  save,
  cascadePending,
  cascadeApplying,
  cascadeConfirm,
  cascadeCancel,
} = usePortConfigEdit(props, { saved: () => emit('saved'), close: () => emit('close') })

const ROLES: PortRole[] = ['none', 'management', 'data', 'management_data']
const MODES: VlanMode[] = ['access', 'trunk']

function dismiss() {
  if (!saving.value && !cascadeApplying.value) emit('close')
}

function manageGroup() {
  emit('manage-ports', { interfaceId: own.value.interfaceId, deviceLabel: own.value.deviceLabel })
}

const vlanLabel = (o: VLANDefinition) => `VLAN ${o.vlan_id}${o.name ? ` · ${o.name}` : ''}${o.domain_name ? ` (${o.domain_name})` : ''}`
</script>

<template>
  <BaseModal @close="dismiss">
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
  </BaseModal>
</template>

<style scoped>
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
