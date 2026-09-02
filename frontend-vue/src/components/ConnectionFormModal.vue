<script setup lang="ts">
// Источник и назначение подключения выбираются в два шага (устройство -> порт),
// т.к. интерфейсы принадлежат конкретному устройству. Список портов на каждом шаге
// исключает уже занятые активным подключением (см. connections store:
// occupiedInterfaceIds) — сервер всё равно отклонит конфликт с 409
// (validate_connection в backend/app/services/validation.py: "один из портов уже
// участвует в другом активном подключении"), но лучше не доводить до этой ошибки.
// При редактировании собственные текущие порты этого подключения не считаются
// занятыми — иначе нельзя было бы просто поменять, например, тип линии связи, не
// трогая порты.
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { Connection, Device, DeviceInterface } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useConnectionsStore } from '../stores/connections'
import QuickAddButton from './QuickAddButton.vue'
import DevicePortsModal from './DevicePortsModal.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

const props = defineProps<{ connection: Connection | null }>()
const emit = defineEmits<{ close: []; saved: [connection: Connection] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const connectionsStore = useConnectionsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.connection !== null)

const PURPOSE_PRESETS = ['Передача данных', 'Управление активами', 'Передача данных и управление активами']

function emptyForm() {
  return {
    sourceDeviceId: '',
    source_interface_id: '',
    destinationDeviceId: '',
    destination_interface_id: '',
    connection_type_id: '',
    purpose: '',
    is_active: true,
    description: '',
  }
}
const form = reactive(emptyForm())

const allInterfaces = computed(() => (catalogs.items['interfaces'] ?? []) as unknown as DeviceInterface[])

function deviceLabel(d: Device) {
  return d.system_name || d.serial_number
}

function interfacesFor(deviceId: string, currentlySelectedId: string): DeviceInterface[] {
  if (!deviceId) return []
  const occupied = connectionsStore.occupiedInterfaceIds
  return allInterfaces.value.filter(
    (i) => i.physical_device_id === deviceId && (i.id === currentlySelectedId || !occupied.has(i.id)),
  )
}

const sourceInterfaces = computed(() => interfacesFor(form.sourceDeviceId, form.source_interface_id))
const destinationInterfaces = computed(() => interfacesFor(form.destinationDeviceId, form.destination_interface_id))

watch(
  () => props.connection,
  (c) => {
    Object.assign(form, emptyForm())
    if (c) {
      const src = allInterfaces.value.find((i) => i.id === c.source_interface_id)
      const dst = allInterfaces.value.find((i) => i.id === c.destination_interface_id)
      form.sourceDeviceId = src?.physical_device_id ?? ''
      form.source_interface_id = c.source_interface_id
      form.destinationDeviceId = dst?.physical_device_id ?? ''
      form.destination_interface_id = c.destination_interface_id
      form.connection_type_id = c.connection_type_id
      form.purpose = c.purpose ?? ''
      form.is_active = c.is_active
      form.description = c.description ?? ''
    }
  },
  { immediate: true },
)

// Смена устройства сбрасывает выбранный порт, если он больше не входит в список
// (иначе можно было бы отправить порт от другого устройства невидимым образом).
watch(
  () => form.sourceDeviceId,
  () => {
    if (!sourceInterfaces.value.some((i) => i.id === form.source_interface_id)) form.source_interface_id = ''
  },
)
watch(
  () => form.destinationDeviceId,
  () => {
    if (!destinationInterfaces.value.some((i) => i.id === form.destination_interface_id)) form.destination_interface_id = ''
  },
)

// Управление портами выбранного устройства прямо отсюда, без ухода в форму устройства (см.
// DevicePortsModal.vue) — какое из двух устройств редактируется, определяет portsEndpoint.
// Кнопка "Порты" в каждом fieldset доступна только когда устройство уже выбрано (иначе неясно,
// чьи порты открывать).
const portsEndpoint = ref<'source' | 'destination' | null>(null)
function openPorts(endpoint: 'source' | 'destination') {
  portsEndpoint.value = endpoint
}
function closePorts() {
  portsEndpoint.value = null
}
const portsDeviceId = computed(() => (portsEndpoint.value === 'source' ? form.sourceDeviceId : form.destinationDeviceId))
const portsDeviceLabel = computed(() => {
  const device = devicesStore.all.find((d) => d.id === portsDeviceId.value)
  return device ? deviceLabel(device) : ''
})
// После сохранения портов список интерфейсов устройства в catalogs.items['interfaces'] уже
// обновлён самой модалкой (см. DevicePortsModal.vue:submit → catalogs.replaceDeviceInterfaces),
// поэтому sourceInterfaces/destinationInterfaces пересчитаются реактивно сами. Остаётся только
// сбросить выбор порта, если он был удалён в модалке, — иначе <select> остался бы указывать на
// id, для которого больше нет <option>.
function onPortsSaved() {
  if (portsEndpoint.value === 'source' && !sourceInterfaces.value.some((i) => i.id === form.source_interface_id)) {
    form.source_interface_id = ''
  }
  if (portsEndpoint.value === 'destination' && !destinationInterfaces.value.some((i) => i.id === form.destination_interface_id)) {
    form.destination_interface_id = ''
  }
  closePorts()
}

async function submit() {
  errorMessage.value = null
  if (!form.source_interface_id) {
    errorMessage.value = 'Выберите исходное устройство и его порт.'
    return
  }
  if (!form.destination_interface_id) {
    errorMessage.value = 'Выберите конечное устройство и его порт.'
    return
  }
  if (form.source_interface_id === form.destination_interface_id) {
    errorMessage.value = 'Исходный и конечный порт не могут совпадать.'
    return
  }
  if (!form.connection_type_id) {
    errorMessage.value = 'Выберите тип физической линии связи.'
    return
  }

  saving.value = true
  try {
    const payload = {
      source_interface_id: form.source_interface_id,
      destination_interface_id: form.destination_interface_id,
      connection_type_id: form.connection_type_id,
      purpose: form.purpose || null,
      is_active: form.is_active,
      description: form.description || null,
    }
    const saved = isEdit.value
      ? await updateResource<Connection>('connections', props.connection!.id, payload)
      : await createResource<Connection>('connections', payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить подключение'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать подключение' : 'Добавить подключение' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form @submit.prevent="submit">
        <div class="endpoint-pair">
          <fieldset class="endpoint">
            <legend>Исходное устройство</legend>
            <label class="field">
              <span>Устройство</span>
              <select v-model="form.sourceDeviceId">
                <option value="">— выберите —</option>
                <option v-for="d in devicesStore.all" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
              </select>
            </label>
            <label class="field">
              <span>Порт *</span>
              <div class="lookup-row">
                <select v-model="form.source_interface_id" :disabled="!form.sourceDeviceId">
                  <option value="">— выберите —</option>
                  <option v-for="i in sourceInterfaces" :key="i.id" :value="i.id">{{ i.name }}</option>
                </select>
                <button
                  type="button"
                  class="quick-add-btn"
                  aria-label="Управлять портами исходного устройства"
                  title="Управлять портами устройства"
                  :disabled="!form.sourceDeviceId"
                  @click="openPorts('source')"
                >
                  <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
                </button>
              </div>
              <small v-if="form.sourceDeviceId && !sourceInterfaces.length" class="hint-small">
                Нет свободных портов — все заняты активными подключениями. Можно добавить новый через «Управлять портами устройства».
              </small>
            </label>
          </fieldset>

          <div class="link-icon">
            <svg class="icon"><use href="/icons.svg#i-network" /></svg>
          </div>

          <fieldset class="endpoint">
            <legend>Конечное устройство</legend>
            <label class="field">
              <span>Устройство</span>
              <select v-model="form.destinationDeviceId">
                <option value="">— выберите —</option>
                <option v-for="d in devicesStore.all" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
              </select>
            </label>
            <label class="field">
              <span>Порт *</span>
              <div class="lookup-row">
                <select v-model="form.destination_interface_id" :disabled="!form.destinationDeviceId">
                  <option value="">— выберите —</option>
                  <option v-for="i in destinationInterfaces" :key="i.id" :value="i.id">{{ i.name }}</option>
                </select>
                <button
                  type="button"
                  class="quick-add-btn"
                  aria-label="Управлять портами конечного устройства"
                  title="Управлять портами устройства"
                  :disabled="!form.destinationDeviceId"
                  @click="openPorts('destination')"
                >
                  <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
                </button>
              </div>
              <small v-if="form.destinationDeviceId && !destinationInterfaces.length" class="hint-small">
                Нет свободных портов — все заняты активными подключениями. Можно добавить новый через «Управлять портами устройства».
              </small>
            </label>
          </fieldset>
        </div>

        <div class="form-grid">
          <label class="field">
            <span>Тип физической линии связи *</span>
            <div class="lookup-row">
              <select v-model="form.connection_type_id">
                <option value="">— выберите —</option>
                <option v-for="t in catalogs.items['connection-types'] ?? []" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
              <QuickAddButton resource="connection-types" title="Тип подключения" @created="(r) => (form.connection_type_id = r.id)" />
            </div>
          </label>

          <label class="field">
            <span>Назначение линии связи</span>
            <input v-model.trim="form.purpose" type="text" list="purpose-presets" maxlength="500" />
            <datalist id="purpose-presets">
              <option v-for="p in PURPOSE_PRESETS" :key="p" :value="p" />
            </datalist>
          </label>

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

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>

    <DevicePortsModal
      v-if="portsEndpoint"
      :device-id="portsDeviceId"
      :device-label="portsDeviceLabel"
      @close="closePorts"
      @saved="onPortsSaved"
    />
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
  color: var(--status-crit);
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
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lookup-row select {
  flex: 1;
  min-width: 0;
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
.hint-small {
  color: var(--status-warn);
  font-size: 10.5px;
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
