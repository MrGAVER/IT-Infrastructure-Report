<script setup lang="ts">
import { useId } from 'vue'
// Форма создания/редактирования подключения. Источник и назначение выбираются в два шага (устройство -> порт), т.к. интерфейсы
// принадлежат конкретному устройству.
//
// Состояние формы и списки устройств/портов — useConnectionDraft; сверка конфигурации пары портов (роль, режим, VLAN) —
// useConnectionPortConfig; управление портами устройства из формы — useConnectionPortsDialog; сохранение и решение по расхождению —
// useConnectionSave (правила «назначения линии связи» и расхождений описаны там). Стороны подключения — ConnectionEndpointFieldset,
// выбор решения по расхождению — ConnectionResolutionPanel.
import type { Connection } from '../api/types'
import type { ConnectionPrefill } from '../utils/connectionForm'
import { sideLabel } from '../utils/connectionPortView'
import { facetsLabel } from '../utils/portConfig'
import QuickAddButton from './QuickAddButton.vue'
import DevicePortsModal from './DevicePortsModal.vue'
import VlanModeCascadeModal from './VlanModeCascadeModal.vue'
import SearchableSelect from './SearchableSelect.vue'
import ConnectionEndpointFieldset from './ConnectionEndpointFieldset.vue'
import ConnectionResolutionPanel from './ConnectionResolutionPanel.vue'
import { useConnectionDraft } from '../composables/useConnectionDraft'
import { useConnectionPortConfig } from '../composables/useConnectionPortConfig'
import { useConnectionPortsDialog } from '../composables/useConnectionPortsDialog'
import { useConnectionSave } from '../composables/useConnectionSave'
import BaseModal from './BaseModal.vue'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{
  connection: Connection | null
  // Фикс п.3.4 (батч4, визуальный режим подключений): при создании подключения перетаскиванием
  // на схеме (см. ConnectionCanvasModal.vue) источник и назначение уже выбраны курсором мыши —
  // остаётся только тип линии связи/назначение/статус, поэтому оба порта форма подставляет сама.
  // Игнорируется, если передан connection (редактирование существующего всегда важнее подсказки
  // для ещё не созданного).
  prefill?: ConnectionPrefill | null
}>()
const emit = defineEmits<{ close: []; saved: [connection: Connection] }>()
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const draft = useConnectionDraft({ connection: () => props.connection, prefill: () => props.prefill })
const {
  saving,
  errorMessage,
  resolving,
  isEdit,
  form,
  deviceOptions,
  sourcePortOptions,
  destinationPortOptions,
  connectionTypeOptions,
  sourceHasNoInterfacesAtAll,
  destinationHasNoInterfacesAtAll,
} = draft

// Порядок вызова важен: подписки (watch) создаются в этом порядке — сначала загрузка формы и сброс порта при смене устройства,
// затем пересчёт сверки пары портов.
const portConfig = useConnectionPortConfig({
  source: () => draft.selectedSourceInterface.value,
  destination: () => draft.selectedDestinationInterface.value,
  connectionId: () => props.connection?.id,
  isActive: () => form.is_active,
})
const { configView, portMismatch, mismatchAlreadyApproved } = portConfig

const portsDialog = useConnectionPortsDialog(draft, portConfig.refresh)
const { submit, resolveAndSave, cancelCascade, cascadePending, cascadeApplying, cascadeConfirm } = useConnectionSave(draft, portConfig, {
  connection: () => props.connection,
  readOnly,
  onSaved: (connection) => emit('saved', connection),
})
</script>

<template>
  <BaseModal @close="emit('close')">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ isEdit ? 'Редактировать подключение' : 'Добавить подключение' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <fieldset class="readonly-fieldset" :disabled="readOnly">
        <form @submit.prevent="submit">
          <div class="endpoint-pair">
            <ConnectionEndpointFieldset
              v-model:device-id="form.sourceDeviceId"
              v-model:interface-id="form.source_interface_id"
              legend="Исходное устройство"
              manage-ports-label="Управлять портами исходного устройства"
              :device-options="deviceOptions"
              :port-options="sourcePortOptions"
              :has-no-ports-at-all="sourceHasNoInterfacesAtAll"
              @manage-ports="portsDialog.open('source')"
            />

            <div class="link-icon">
              <svg class="icon"><use href="/icons.svg#i-network" /></svg>
            </div>

            <ConnectionEndpointFieldset
              v-model:device-id="form.destinationDeviceId"
              v-model:interface-id="form.destination_interface_id"
              legend="Конечное устройство"
              manage-ports-label="Управлять портами конечного устройства"
              :device-options="deviceOptions"
              :port-options="destinationPortOptions"
              :has-no-ports-at-all="destinationHasNoInterfacesAtAll"
              @manage-ports="portsDialog.open('destination')"
            />
          </div>

          <div class="form-grid">
            <label class="field">
              <span>Тип физической линии связи *</span>
              <div class="lookup-row">
                <SearchableSelect v-model="form.connection_type_id" :options="connectionTypeOptions" placeholder="— выберите —" />
                <QuickAddButton resource="connection-types" title="Тип подключения" @created="(r) => (form.connection_type_id = r.id)" />
              </div>
            </label>

            <!-- Конфигурация портов (роль, режим, VLAN): роли — единственный источник «назначения линии
               связи» (см. useConnectionSave). При расхождении сохранение потребует явного решения.
               Сверку делает сервер (см. useConnectionPortConfig). -->
            <div v-if="configView" class="field field-wide port-roles" :class="{ mismatch: portMismatch }">
              <span class="port-roles-title">Конфигурация портов</span>
              <span v-for="side in [configView.source, configView.destination]" :key="side.id" class="port-roles-row">
                <span class="mono">{{ side.name }}</span> — {{ sideLabel(side) }}
              </span>
              <span v-if="portMismatch && !mismatchAlreadyApproved" class="warning-text">
                ⚠ Конфигурации портов различаются ({{ facetsLabel(portMismatch.diff) }}). При сохранении нужно будет выбрать решение: выровнять порты или
                одобрить расхождение.
              </span>
              <span v-else-if="mismatchAlreadyApproved" class="approved-text">✓ Расхождение ({{ facetsLabel(portMismatch!.diff) }}) одобрено ранее.</span>
            </div>

            <label class="field checkbox-field">
              <input v-model="form.is_active" type="checkbox" />
              <span>Подключение активно</span>
            </label>

            <label class="field field-wide">
              <span>Описание</span>
              <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
            </label>
          </div>
        </form>
      </fieldset>

      <ConnectionResolutionPanel v-if="resolving && portMismatch" :mismatch="portMismatch" @resolve="resolveAndSave" @back="resolving = false" />

      <div v-else class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>

    <DevicePortsModal
      v-if="portsDialog.endpoint.value"
      :device-id="portsDialog.deviceId.value"
      :device-label="portsDialog.deviceLabel.value"
      @close="portsDialog.close"
      @saved="portsDialog.onSaved"
    />

    <VlanModeCascadeModal
      v-if="cascadePending"
      :plan="cascadePending.plan"
      :applying="cascadeApplying"
      :port-label="cascadePending.portLabel"
      @confirm="cascadeConfirm"
      @cancel="cancelCascade"
    />
  </BaseModal>
</template>

<style scoped>
.modal {
  width: 100%;
  max-width: 680px;
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
.endpoint-pair {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 10px;
  align-items: start;
  margin-bottom: 16px;
}
.link-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding-top: 26px;
  color: var(--ink-muted);
}
.link-icon .icon {
  width: 18px;
  height: 18px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field-wide {
  grid-column: 1 / -1;
}
.port-roles {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--surface-2);
}
.port-roles.mismatch {
  border-color: var(--status-warn);
  background: var(--status-warn-soft);
}
.port-roles-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.port-roles-row {
  font-size: 12.5px;
  color: var(--ink);
}
.port-roles .warning-text {
  font-size: 12px;
  color: var(--ink);
  line-height: 1.4;
}
.port-roles .approved-text {
  font-size: 12px;
  color: var(--status-ok, var(--ink));
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lookup-row select {
  flex: 1;
  min-width: 0;
}
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.field select:disabled {
  opacity: 0.5;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12.5px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .endpoint-pair {
    grid-template-columns: 1fr;
  }
  .link-icon {
    padding-top: 0;
    transform: rotate(90deg);
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
