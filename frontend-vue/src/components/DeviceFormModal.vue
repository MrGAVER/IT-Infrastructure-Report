<script setup lang="ts">
// Форма создания/редактирования устройства.
//
// Состояние формы — useDeviceDraft; загрузка (редактирование или копия донора) — useDeviceLoader; сохранение с подтверждением
// конфликтов 409 — useDeviceSave; домены VLAN, VLAN портов и общие настройки VLAN стека — useDeviceDomains, useDevicePortVlans,
// useDeviceStackVlans; основные поля и их справочники — useDeviceFormFields.
import { ref } from 'vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useFormPreferencesStore } from '../stores/formPreferences'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'
import { useDeviceDomains } from '../composables/useDeviceDomains'
import { useDeviceDraft } from '../composables/useDeviceDraft'
import { useDeviceFormFields } from '../composables/useDeviceFormFields'
import { useDeviceLoader } from '../composables/useDeviceLoader'
import { useDevicePortVlans } from '../composables/useDevicePortVlans'
import { useDeviceSave } from '../composables/useDeviceSave'
import { useDeviceStackVlans } from '../composables/useDeviceStackVlans'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import type { Device } from '../api/types'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import DeviceVlanListEditor from './DeviceVlanListEditor.vue'
import DeviceStackVlanIpEditor from './DeviceStackVlanIpEditor.vue'
import DeviceIconPicker from './DeviceIconPicker.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ device: Device | null; copyFrom?: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

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
const { availableVlans, singleDeviceDomainId, joinableDomains, memberDomains, onVlanCreated, onVlanDomainCreated, onJoinDomainRequested, onCancelJoinDomain } = domains
const { deviceStackId, lockedStackVlans, onStackVlanState, onStackVlanApplied, onStackVlanRemoved } = useDeviceStackVlans(draft, () => props.device)
// Порядок вызова важен: подписки (watch) создаются в этом порядке — VLAN портов, затем загрузка источника (она же следит за
// типом устройства), затем каскад полей формы.
const { portVlanOptions } = useDevicePortVlans(draft, { revealStaleSubinterfaces: () => void interfacesEditor.value?.revealStaleSubinterfaces() })
const { reloadNeighborConfigs } = useDeviceLoader(draft, { device: () => props.device, copyFrom: () => props.copyFrom })
const { operatingSystemOptions, embeddedOsOptions, buildingOptions, roomOptions, rackOptions, roomQuickAddValues, rackQuickAddValues, rackQuickAddScope, typeModelOptions, typeModelSelection, onModelCreated, onRoomCreated, onRackCreated } =
  useDeviceFormFields(form)

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
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать устройство' : 'Добавить устройство' }}</h2>
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
        <!-- п.3.6: три поля (Тип устройства/Производитель/Модель) объединены в одно — единственный
             select с опциями "голых" типов (без модели) и моделей, сгруппированных по
             производителю. См. typeModelSelection/modelGroups в <script setup>. -->
        <label class="field field-wide">
          <span>Тип / производитель / модель *</span>
          <div class="lookup-row">
            <SearchableSelect v-model="typeModelSelection" :options="typeModelOptions" placeholder="— выберите —" />
            <QuickAddButton resource="device-models" title="Модель устройства" @created="onModelCreated" />
          </div>
        </label>

        <label class="field">
          <span>Серийный номер *</span>
          <input v-model.trim="form.serial_number" v-truncate-tooltip="form.serial_number" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Системное имя</span>
          <input v-model.trim="form.system_name" v-truncate-tooltip="form.system_name" type="text" maxlength="255" />
        </label>

        <label class="field">
          <span>Операционная система</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.operating_system_id" :options="operatingSystemOptions" placeholder="— не указана —" />
            <QuickAddButton resource="operating-systems" title="Операционная система" @created="(r) => (form.operating_system_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Встроенная ОС (для сетевого оборудования)</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.embedded_os_id" :options="embeddedOsOptions" placeholder="— не указана —" />
            <QuickAddButton resource="embedded-os" title="Встроенная ОС" @created="(r) => (form.embedded_os_id = r.id)" />
          </div>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.siem_enabled" type="checkbox" />
          <span>Отправляет события в SIEM</span>
        </label>

        <label class="field">
          <span>Здание</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.building_id" :options="buildingOptions" placeholder="— не указано —" />
            <QuickAddButton resource="buildings" title="Здание" @created="(r) => (form.building_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Помещение</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.room_id" :options="roomOptions" :disabled="!form.building_id" placeholder="— не указано —" />
            <QuickAddButton resource="rooms" title="Помещение" :initial-values="roomQuickAddValues" @created="onRoomCreated" />
          </div>
        </label>

        <label class="field">
          <span>Стойка</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.rack_id" :options="rackOptions" :disabled="!form.room_id" placeholder="— не указана —" />
            <QuickAddButton resource="racks" title="Стойка" :initial-values="rackQuickAddValues" :fk-scope="rackQuickAddScope" @created="onRackCreated" />
          </div>
        </label>

        <label class="field">
          <span>Позиция в стойке</span>
          <input v-model.trim="form.rack_position" v-truncate-tooltip="form.rack_position" type="text" placeholder="напр. 12U" maxlength="50" />
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <div class="field field-wide oac-cert-block">
          <div class="oac-cert-head">
            <b>Сертификат ОАЦ</b>
            <span class="hint">Необязательно — заполняется, если на устройстве установлено сертифицированное средство криптографической защиты информации.</span>
          </div>
          <div class="oac-cert-grid">
            <label class="field">
              <span>Регистрационный номер сертификата соответствия (экспертного заключения)</span>
              <input
                v-model.trim="form.oac_certificate_number"
                v-truncate-tooltip="form.oac_certificate_number"
                type="text"
                maxlength="255"
              />
            </label>
            <label class="field">
              <span>Дата внесения в реестр</span>
              <input v-model="form.oac_certificate_registry_date" type="date" />
            </label>
          </div>
        </div>

        <div class="field field-wide">
          <DeviceIconPicker :model-value="form.diagram_icon_id || null" @update:model-value="form.diagram_icon_id = $event ?? ''" />
        </div>

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
  color: var(--status-crit);
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
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
  /* п.3.2: без min-width:0 ячейка CSS-грида не сжимается ниже intrinsic-ширины своего
     содержимого — длинный текст в select/input (например, длинное имя помещения) распирал
     ячейку шире её грид-трека и вылезал за пределы скруглённой подложки модалки (.modal). */
  min-width: 0;
}
.field-wide {
  grid-column: 1 / -1;
}
.oac-cert-block {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  gap: 10px;
}
.oac-cert-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.oac-cert-head b {
  font-size: 12.5px;
  color: var(--ink);
}
.oac-cert-head .hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.oac-cert-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
@media (max-width: 640px) {
  .oac-cert-grid {
    grid-template-columns: 1fr;
  }
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.lookup-row select,
.lookup-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.field input[type='text'],
.field input[type='date'],
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
/* Фикс: "Дата внесения в реестр" (единственный input[type=date] в этой форме) визуально
   выпадала из стиля проекта — селектор выше раньше подхватывал только input[type='text'], а
   тёмная тема приложения (theme.css) нигде не объявляет color-scheme, поэтому нативные иконка
   календаря и всплывающий пикер браузера всегда светлые поверх тёмного инпута. color-scheme
   переключает именно их палитру на тёмную, ничего в разметке/поведении не меняя; ширина/фон/
   рамка самого поля уже выровнены общим правилом выше. Область действия — только это поле, а
   не вся тема, т.к. остальные нативные контролы приложения (например, <select>) решены иначе —
   собственным SearchableSelect.vue, а не color-scheme. */
.oac-cert-grid input[type='date'] {
  color-scheme: dark;
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
