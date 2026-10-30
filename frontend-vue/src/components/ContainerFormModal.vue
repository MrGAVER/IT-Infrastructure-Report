<script setup lang="ts">
// Контейнер размещается либо на ВМ, либо напрямую на физическом устройстве, либо нигде
// конкретно не указан — модель допускает оба FK одновременно (backend/app/models.py:Container),
// но семантически это альтернативы, как source_type в ISSourcesListEditor.vue, только без
// варианта "вручную" (у контейнера нет своего IP на уровне отчёта). hostType — локальное поле
// формы, не персистится само по себе: при сохранении в payload попадает только тот из двух FK,
// что соответствует выбранному типу, второй всегда null.
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { Container, Device } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'
import { filterHostDevices } from '../utils/deviceFilters'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ container: Container | null; copyFrom?: Container | null }>()
const emit = defineEmits<{ close: []; saved: [container: Container] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const vmsStore = useVMsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.container !== null)

const hostDevices = computed<Device[]>(() => filterHostDevices(devicesStore.all, catalogs))

function deviceLabel(d: Device): string {
  return d.system_name || d.serial_number
}

type HostType = 'none' | 'vm' | 'device'

function emptyForm() {
  return {
    name: '',
    hostType: 'none' as HostType,
    virtual_machine_id: '',
    physical_device_id: '',
    runtime: '',
    runtime_version: '',
    purpose: '',
  }
}
const form = reactive(emptyForm())

// Фикс п.2 (копирование): container.name у Container не уникален (в отличие от PhysicalDevice.
// serial_number / InformationSystem.name / VirtualMachine.name — см. их формы), поэтому копию
// можно сохранить с тем же именем без конфликта — очищать/менять здесь нечего, в отличие от
// остальных трёх сущностей.
watch(
  () => props.container ?? props.copyFrom ?? null,
  (c) => {
    // Аудит fix/usability-batch4 (находка №5): см. подробный комментарий в DeviceFormModal.vue.
    if (props.container && props.copyFrom) {
      console.warn('ContainerFormModal: одновременно переданы container и copyFrom — используется container (режим редактирования)')
    }
    Object.assign(form, emptyForm())
    if (c) {
      form.name = c.name
      form.virtual_machine_id = c.virtual_machine_id ?? ''
      form.physical_device_id = c.physical_device_id ?? ''
      form.hostType = c.virtual_machine_id ? 'vm' : c.physical_device_id ? 'device' : 'none'
      form.runtime = c.runtime ?? ''
      form.runtime_version = c.runtime_version ?? ''
      form.purpose = c.purpose ?? ''
    }
  },
  { immediate: true },
)

function onHostTypeChange(type: string) {
  form.hostType = type as HostType
  form.virtual_machine_id = ''
  form.physical_device_id = ''
}

function toPayload() {
  return {
    name: form.name.trim(),
    virtual_machine_id: form.hostType === 'vm' ? form.virtual_machine_id || null : null,
    physical_device_id: form.hostType === 'device' ? form.physical_device_id || null : null,
    runtime: form.runtime.trim() || null,
    runtime_version: form.runtime_version.trim() || null,
    purpose: form.purpose.trim() || null,
  }
}

async function submit() {
  if (readOnly.value) return
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование контейнера.'
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    const saved = isEdit.value
      ? await updateResource<Container>('containers', props.container!.id, payload)
      : await createResource<Container>('containers', payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить контейнер'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать контейнер' : 'Добавить контейнер' }}</h2>
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
          <label class="field field-wide">
            <span>Наименование *</span>
            <input v-model.trim="form.name" type="text" required maxlength="255" />
          </label>

          <label class="field">
            <span>Размещение</span>
            <select :value="form.hostType" @change="onHostTypeChange(($event.target as HTMLSelectElement).value)">
              <option value="none">— не указано —</option>
              <option value="vm">Виртуальная машина</option>
              <option value="device">Физическое устройство</option>
            </select>
          </label>

          <label class="field">
            <span>Виртуальная машина</span>
            <select v-model="form.virtual_machine_id" :disabled="form.hostType !== 'vm'">
              <option value="">— выберите ВМ —</option>
              <option v-for="vm in vmsStore.all" :key="vm.id" :value="vm.id">{{ vm.name }}</option>
            </select>
          </label>

          <label class="field">
            <span>Физическое устройство</span>
            <select v-model="form.physical_device_id" :disabled="form.hostType !== 'device'">
              <option value="">— выберите устройство —</option>
              <option v-for="d in hostDevices" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
            </select>
          </label>

          <label class="field">
            <span>Runtime</span>
            <input v-model.trim="form.runtime" type="text" placeholder="Docker, containerd…" maxlength="100" />
          </label>

          <label class="field">
            <span>Версия runtime</span>
            <input v-model.trim="form.runtime_version" type="text" maxlength="100" />
          </label>

          <label class="field field-wide">
            <span>Целевое назначение</span>
            <textarea v-model.trim="form.purpose" rows="2" maxlength="2000"></textarea>
          </label>
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
.field input,
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
  opacity: 0.45;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
