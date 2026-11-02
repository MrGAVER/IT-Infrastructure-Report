<script setup lang="ts">
// Форма создания/редактирования устройства.
//
// Состояние формы — useDeviceDraft; загрузка (редактирование или копия донора) — useDeviceLoader; сохранение с подтверждением
// конфликтов 409 — useDeviceSave; домены VLAN, VLAN портов и общие настройки VLAN стека — useDeviceDomains, useDevicePortVlans,
// useDeviceStackVlans. Основные поля формы и их справочники — DeviceMainFields (useDeviceFormFields).
import { ref, useId } from 'vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useFormPreferencesStore } from '../stores/formPreferences'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'
import { useDeviceDomains } from '../composables/useDeviceDomains'
import { useDeviceDraft } from '../composables/useDeviceDraft'
import { useDeviceLoader } from '../composables/useDeviceLoader'
import { useDevicePortVlans } from '../composables/useDevicePortVlans'
import { useDeviceSave } from '../composables/useDeviceSave'
import { useDeviceStackVlans } from '../composables/useDeviceStackVlans'
import type { Device } from '../api/types'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import DeviceVlanListEditor from './DeviceVlanListEditor.vue'
import DeviceStackVlanIpEditor from './DeviceStackVlanIpEditor.vue'
import DeviceMainFields from './DeviceMainFields.vue'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ device: Device | null; copyFrom?: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const formPreferences = useFormPreferencesStore()

const draft = useDeviceDraft(() => props.device)
const { errorMessage, isEdit, form, softwareAssets, interfaces, interfaceGroups, deviceVlans, loadingNested, initialConnections, interfaceConflicts } = draft

// Редактор портов: перед записью проверяет расхождения с соседями (reviewNeighborMismatches).
const interfacesEditor = ref<InstanceType<typeof DeviceInterfacesEditor> | null>(null)
// Блок «VLAN устройства»: форма раскрывает его, когда ошибка сохранения относится к строке, скрытой сворачиванием.
const vlanEditor = ref<InstanceType<typeof DeviceVlanListEditor> | null>(null)

const domains = useDeviceDomains(draft)
const { availableVlans, singleDeviceDomainId, joinableDomains, memberDomains, onVlanCreated, onVlanDomainCreated, onJoinDomainRequested, onCancelJoinDomain } =
  domains
const { deviceStackId, lockedStackVlans, onStackVlanState, onStackVlanApplied, onStackVlanRemoved } = useDeviceStackVlans(draft, () => props.device)
// Порядок вызова важен: подписки (watch) создаются в этом порядке — VLAN портов, затем загрузка источника (она же следит за
// типом устройства); каскад полей формы создаёт DeviceMainFields при монтировании, то есть последним.
const { portVlanOptions } = useDevicePortVlans(draft, { revealStaleSubinterfaces: () => void interfacesEditor.value?.revealStaleSubinterfaces() })
const { reloadNeighborConfigs } = useDeviceLoader(draft, { device: () => props.device, copyFrom: () => props.copyFrom })

const { saving, submit } = useDeviceSave(draft, {
  device: () => props.device,
  readOnly,
  domains,
  portVlanOptions,
  reviewNeighbors: (initial) => interfacesEditor.value?.reviewNeighborMismatches(initial),
  expandVlanEditor: () => vlanEditor.value?.expand(),
  onSaved: (device) => emit('saved', device),
})
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ isEdit ? 'Редактировать устройство' : 'Добавить устройство' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <fieldset class="readonly-fieldset" :disabled="readOnly">
        <form class="form-grid" @submit.prevent="submit">
          <DeviceMainFields :model-value="form" />

          <p v-if="loadingNested" class="loading-hint field-wide">Загрузка портов, ПО, интерфейсов и VLAN…</p>
          <SoftwareAssetListEditor v-if="!loadingNested" v-model="softwareAssets" :catalog-entries="catalogs.items['software-assets'] ?? []" />
          <DeviceInterfacesEditor
            v-if="!loadingNested"
            ref="interfacesEditor"
            v-model="interfaces"
            v-model:groups="interfaceGroups"
            :type-options="catalogs.items['interface-types'] ?? []"
            :speed-options="catalogs.items['interface-speeds'] ?? []"
            :vlan-options="portVlanOptions"
            :vlan-catalog="vlansStore.allDefinitions"
            :conflicts="interfaceConflicts"
            :protocol-port-catalog="catalogs.protocolPortCatalog"
            :device-id="props.device?.id ?? null"
            :device-label="form.system_name || form.serial_number"
            edit-connections
            :connection-baseline="initialConnections"
            @neighbors-changed="reloadNeighborConfigs"
          />
          <DeviceVlanListEditor
            v-if="!loadingNested"
            ref="vlanEditor"
            v-model="deviceVlans"
            :collapse-after="formPreferences.collapseRows"
            :vlan-options="availableVlans"
            :all-vlan-definitions="vlansStore.allDefinitions"
            :device-domain-id="singleDeviceDomainId"
            :joinable-domains="joinableDomains"
            :member-domains="memberDomains"
            :locked-vlans="lockedStackVlans"
            @cancel-join-domain="onCancelJoinDomain"
            @vlan-created="onVlanCreated"
            @vlan-domain-created="onVlanDomainCreated"
            @join-domain="onJoinDomainRequested"
          />
          <DeviceStackVlanIpEditor
            v-if="deviceStackId && !loadingNested"
            :stack-id="deviceStackId"
            :reload-token="0"
            @update:state="onStackVlanState"
            @applied="onStackVlanApplied"
            @removed="onStackVlanRemoved"
          />
        </form>
      </fieldset>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>
  </div>
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
  /* Список интерфейсов (DeviceInterfacesEditor.vue) — таблица из 10 колонок; на типичных
     (не сверхширoких) десктопных окнах 50vw заметно уже, чем ей нужно, и до кнопок удаления и
     "Применить к выбранным" в последней колонке приходится прокручивать таблицу горизонтально.
     Увеличенные 70vw/1400px дают заметно больше места именно на таких окнах (напр. 1440px
     окно: было 720px, стало ~1008px), а нижняя граница 640px не меняется — на узких экранах
     ничего не задевает, и там же по-прежнему работает .iface-table-wrap { overflow-x: auto }
     как запасной вариант. */
  max-width: clamp(640px, 70vw, 1400px);
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
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
/* Свой экземпляр правила (а не из DeviceMainFields): им пользуются строка загрузки и корень DeviceStackVlanIpEditor — scoped-стиль
   родителя достаётся корню дочернего компонента. */
.field-wide {
  grid-column: 1 / -1;
}
.loading-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
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
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
