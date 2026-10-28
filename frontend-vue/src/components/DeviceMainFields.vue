<script setup lang="ts">
// Основные поля формы устройства (DeviceFormModal.vue): тип/производитель/модель, серийный номер и системное имя, ОС, SIEM,
// расположение (здание → помещение → стойка), описание, сертификат ОАЦ и иконка диаграммы.
//
// Компонент — фрагмент: его поля становятся прямыми ячейками сетки .form-grid родителя (без обёртки). Форма — reactive-объект
// родителя (useDeviceDraft), правится на месте: на её поля подписаны загрузчик и каскады, поэтому объект не заменяется копией.
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { useDeviceFormFields } from '../composables/useDeviceFormFields'
import type { DeviceForm } from '../utils/deviceForm'
import DeviceIconPicker from './DeviceIconPicker.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'

const form = defineModel<DeviceForm>({ required: true })

// Подписки каскада здание → помещение → стойка создаются при монтировании — уже после подписок родителя (загрузка источника),
// поэтому начальное заполнение формы каскады не запускает.
const { operatingSystemOptions, embeddedOsOptions, buildingOptions, roomOptions, rackOptions, roomQuickAddValues, rackQuickAddValues, rackQuickAddScope, typeModelOptions, typeModelSelection, onModelCreated, onRoomCreated, onRackCreated } =
  useDeviceFormFields(form.value)
</script>

<template>
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
</template>

<style scoped>
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
</style>
