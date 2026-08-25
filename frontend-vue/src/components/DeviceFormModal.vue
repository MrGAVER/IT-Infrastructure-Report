<script setup lang="ts">
// Форма создания/редактирования устройства.
//
// Повторяет логику подтверждения конфликтов из текущего vanilla-фронтенда
// (frontend/static/app.js:saveForm) для консистентности UX: два специфичных
// кода 409-ошибки (см. backend/app/constants.py:ErrorCode) предлагают
// подтверждение через window.confirm() и повторную отправку с флагом, вместо
// того чтобы просто показать ошибку и заставить пользователя вводить всё заново.
import { computed, reactive, ref, watch } from 'vue'
import { ApiError, createResource, deleteResource, listResource, updateResource, ErrorCode } from '../api/client'
import type { Device, DeviceModel, Rack, Room, OpenPort, OpenPortDraftRow } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import OpenPortListEditor from './OpenPortListEditor.vue'

const props = defineProps<{ device: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()

const catalogs = useCatalogsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.device !== null)

function emptyForm() {
  return {
    device_type_id: '',
    manufacturer_id: '',
    model_id: '',
    serial_number: '',
    system_name: '',
    operating_system_id: '',
    embedded_os_id: '',
    siem_enabled: false,
    building_id: '',
    room_id: '',
    rack_id: '',
    rack_position: '',
    description: '',
  }
}

const form = reactive(emptyForm())

// Открытые порты устройства — staged локально, персистятся после сохранения самого устройства
// (нужен его id), по той же схеме delete-затем-recreate, что и для ВМ, см. VMFormModal.vue.
// OpenPortListEditor.vue переиспользован как есть (не знает про owner_type/owner_id).
const openPorts = ref<OpenPortDraftRow[]>([])
const loadingNested = ref(false)

function toOpenPortDraftRow(x: OpenPort): OpenPortDraftRow {
  return {
    id: x.id,
    protocol_catalog_id: x.protocol_catalog_id ?? '',
    port: String(x.port),
    protocol: x.protocol ?? '',
    transport_protocol: x.transport_protocol,
    description: x.description ?? '',
  }
}

watch(
  () => props.device,
  async (d) => {
    Object.assign(form, emptyForm())
    openPorts.value = []
    if (d) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = d[key as keyof Device]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
    }
    if (!d) return
    loadingNested.value = true
    try {
      const ports = await listResource<OpenPort>('open-ports', { owner_type: 'physical_device', owner_id: d.id, limit: 1000 })
      openPorts.value = ports.items.map(toOpenPortDraftRow)
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить открытые порты устройства'
    } finally {
      loadingNested.value = false
    }
  },
  { immediate: true },
)

// Каскадные списки: модель — по выбранному типу устройства, помещение — по
// зданию, стойка — по помещению. Тот же принцип, что связка building_id/room_id
// в фильтре DevicesView, только здесь ещё и сама форма подсказывает валидные
// сочетания вместо того, чтобы полагаться только на серверную валидацию.
const deviceModels = computed(() => catalogs.items['device-models'] as unknown as DeviceModel[])
const rooms = computed(() => catalogs.items['rooms'] as unknown as Room[])
const racks = computed(() => catalogs.items['racks'] as unknown as Rack[])

const filteredModels = computed(() =>
  (deviceModels.value ?? []).filter((m) => !form.device_type_id || m.device_type_id === form.device_type_id),
)
const filteredRooms = computed(() =>
  (rooms.value ?? []).filter((r) => !form.building_id || r.building_id === form.building_id),
)
const filteredRacks = computed(() =>
  (racks.value ?? []).filter((r) => !form.room_id || r.room_id === form.room_id),
)

// Сброс зависимых полей при смене родителя — иначе можно оставить room_id от
// другого здания невидимым в списке, но по-прежнему отправляемым в payload.
watch(
  () => form.device_type_id,
  () => {
    if (!filteredModels.value.some((m) => m.id === form.model_id)) form.model_id = ''
  },
)
watch(
  () => form.building_id,
  () => {
    if (!filteredRooms.value.some((r) => r.id === form.room_id)) form.room_id = ''
  },
)
watch(
  () => form.room_id,
  () => {
    if (!filteredRacks.value.some((r) => r.id === form.rack_id)) form.rack_id = ''
  },
)

function toPayload(extra?: Record<string, unknown>) {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return { ...payload, ...extra }
}

// Delete-затем-recreate — тот же приём и то же обоснование (маленькие списки, простота важнее
// diff-логики), что persistVmIps()/persistOpenPorts() в VMFormModal.vue.
async function persistOpenPorts(deviceId: string) {
  const existing = await listResource<OpenPort>('open-ports', { owner_type: 'physical_device', owner_id: deviceId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('open-ports', old.id)
  }
  for (const row of openPorts.value) {
    if (!row.port.trim()) continue // port NOT NULL на бэкенде, см. VMFormModal.vue
    await createResource<OpenPort>('open-ports', {
      owner_type: 'physical_device',
      owner_id: deviceId,
      protocol_catalog_id: row.protocol_catalog_id || null,
      port: Number(row.port),
      protocol: row.protocol || null,
      transport_protocol: row.transport_protocol || 'TCP',
      description: row.description || null,
    })
  }
}

async function submit() {
  errorMessage.value = null
  if (!form.device_type_id) {
    errorMessage.value = 'Укажите тип устройства.'
    return
  }
  if (!form.serial_number.trim()) {
    errorMessage.value = 'Укажите серийный номер.'
    return
  }

  saving.value = true
  try {
    let extra: Record<string, unknown> | undefined
    // До трёх попыток: обычная отправка, затем до двух ре-отправок с флагами
    // подтверждения, если пользователь согласился на диалоге.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const payload = toPayload(extra)
        const saved = isEdit.value
          ? await updateResource<Device>('devices', props.device!.id, payload)
          : await createResource<Device>('devices', payload)
        await persistOpenPorts(saved.id)
        emit('saved', saved)
        return
      } catch (err) {
        if (err instanceof ApiError && err.code === ErrorCode.DUPLICATE_SYSTEM_NAME && confirm(err.message + '\n\nОК — сохранить дубликат.')) {
          extra = { ...extra, confirm_system_name_duplicate: true }
          continue
        }
        if (err instanceof ApiError && err.code === ErrorCode.RACK_POSITION_OCCUPIED && confirm(err.message)) {
          extra = { ...extra, confirm_rack_position_reassign: true }
          continue
        }
        throw err
      }
    }
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить устройство'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="$emit('close')">
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

      <form class="form-grid" @submit.prevent="submit">
        <label class="field">
          <span>Тип устройства *</span>
          <select v-model="form.device_type_id" required>
            <option value="">— выберите —</option>
            <option v-for="t in catalogs.items['device-types'] ?? []" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Серийный номер *</span>
          <input v-model.trim="form.serial_number" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Системное имя</span>
          <input v-model.trim="form.system_name" type="text" maxlength="255" />
        </label>

        <label class="field">
          <span>Производитель</span>
          <select v-model="form.manufacturer_id">
            <option value="">— не указан —</option>
            <option v-for="m in catalogs.items['manufacturers'] ?? []" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Модель</span>
          <select v-model="form.model_id">
            <option value="">— не указана —</option>
            <option v-for="m in filteredModels" :key="m.id" :value="m.id">{{ m.model }}</option>
          </select>
        </label>

        <label class="field">
          <span>Операционная система</span>
          <select v-model="form.operating_system_id">
            <option value="">— не указана —</option>
            <option v-for="os in catalogs.items['operating-systems'] ?? []" :key="os.id" :value="os.id">
              {{ catalogs.label('operating-systems', os.id) }}
            </option>
          </select>
        </label>

        <label class="field">
          <span>Встроенная ОС (для сетевого оборудования)</span>
          <select v-model="form.embedded_os_id">
            <option value="">— не указана —</option>
            <option v-for="os in catalogs.items['embedded-os'] ?? []" :key="os.id" :value="os.id">
              {{ catalogs.label('embedded-os', os.id) }}
            </option>
          </select>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.siem_enabled" type="checkbox" />
          <span>Отправляет события в SIEM</span>
        </label>

        <label class="field">
          <span>Здание</span>
          <select v-model="form.building_id">
            <option value="">— не указано —</option>
            <option v-for="b in catalogs.items['buildings'] ?? []" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Помещение</span>
          <select v-model="form.room_id" :disabled="!form.building_id">
            <option value="">— не указано —</option>
            <option v-for="r in filteredRooms" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Стойка</span>
          <select v-model="form.rack_id" :disabled="!form.room_id">
            <option value="">— не указана —</option>
            <option v-for="r in filteredRacks" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Позиция в стойке</span>
          <input v-model.trim="form.rack_position" type="text" placeholder="напр. 12U" maxlength="50" />
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <p v-if="loadingNested" class="loading-hint field-wide">Загрузка открытых портов…</p>
        <OpenPortListEditor v-else v-model="openPorts" :catalog-entries="catalogs.protocolPortCatalog" />
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
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
  max-width: 640px;
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
}
.field-wide {
  grid-column: 1 / -1;
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
