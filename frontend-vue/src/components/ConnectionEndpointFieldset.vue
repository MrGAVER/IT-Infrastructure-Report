<script setup lang="ts">
// Одна сторона подключения в форме (ConnectionFormModal.vue): устройство → порт, кнопка «Управлять портами» и подсказка, если
// выбрать нечего. Используется дважды — для исходного и для конечного устройства. Компонент ничего не загружает и не сохраняет:
// выбор отдаёт родителю через v-model, управление портами — событием manage-ports.
import { computed } from 'vue'
import SearchableSelect, { type SearchableSelectOption } from './SearchableSelect.vue'

const props = defineProps<{
  legend: string
  /** Подпись кнопки «Управлять портами» для скринридера: отличает исходную сторону от конечной. */
  managePortsLabel: string
  deviceOptions: SearchableSelectOption[]
  /** Свободные порты выбранного устройства (уже без занятых активными подключениями). */
  portOptions: SearchableSelectOption[]
  /** У устройства нет ни одного порта вообще — это не то же самое, что «все порты заняты». */
  hasNoPortsAtAll: boolean
}>()
defineEmits<{ 'manage-ports': [] }>()

const deviceId = defineModel<string>('deviceId', { required: true })
const interfaceId = defineModel<string>('interfaceId', { required: true })

const allPortsBusy = computed(() => deviceId.value !== '' && props.portOptions.length === 0)
</script>

<template>
  <fieldset class="endpoint">
    <legend>{{ legend }}</legend>
    <label class="field">
      <span>Устройство</span>
      <SearchableSelect v-model="deviceId" :options="deviceOptions" placeholder="— выберите —" />
    </label>
    <label class="field">
      <span>Порт *</span>
      <div class="lookup-row">
        <SearchableSelect v-model="interfaceId" :options="portOptions" :disabled="!deviceId" placeholder="— выберите —" />
        <button
          type="button"
          class="quick-add-btn"
          :aria-label="managePortsLabel"
          title="Управлять портами устройства"
          :disabled="!deviceId"
          @click="$emit('manage-ports')"
        >
          <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
        </button>
      </div>
      <small v-if="hasNoPortsAtAll" class="hint-small">
        У устройства пока нет ни одного порта. Добавьте через «Управлять портами устройства».
      </small>
      <small v-else-if="allPortsBusy" class="hint-small">
        Нет свободных портов — все заняты активными подключениями. Можно добавить новый через «Управлять портами устройства».
      </small>
    </label>
  </fieldset>
</template>

<style scoped>
.endpoint {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
}
.endpoint legend {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0 4px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.quick-add-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--r-s);
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--ink-muted);
  cursor: pointer;
}
.quick-add-btn:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand);
}
.quick-add-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.quick-add-btn .icon {
  width: 14px;
  height: 14px;
}
.hint-small {
  color: var(--status-warn);
  font-size: 10.5px;
}
</style>
