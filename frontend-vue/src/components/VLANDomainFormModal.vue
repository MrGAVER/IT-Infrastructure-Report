<script setup lang="ts">
// Форма VLAN-домена. В отличие от generic-формы vanilla-версии (core.js:FORM_FIELDS —
// только name/description/auto_sync), здесь дополнительно редактируется source_device_id и
// состав участников — иначе домен, созданный через новый UI, никогда нельзя было бы
// синхронизировать (backend/app/api/system.py:sync_vlan_domain требует source_device_id), а
// единственный способ добавить участника в vanilla — косвенный, через "Создать домен VLAN" в
// редакторе VLAN устройства (см. DeviceVlanListEditor.vue), который сюда не перенесён.
//
// Управление составом доступно только при редактировании УЖЕ СУЩЕСТВУЮЩЕГО домена: добавление
// участника идёт через POST /vlan-domains/{id}/members, которому нужен реальный id домена —
// для новой записи его ещё нет. Сохраните домен один раз, затем откройте его снова, чтобы
// добавлять участников.
import { computed, reactive, ref, watch } from 'vue'
import { api, createResource, deleteResource, listResource, updateResource } from '../api/client'
import type { Device, VLANDomain, VLANDomainDeviceLink } from '../api/types'
import { useDevicesStore } from '../stores/devices'

const props = defineProps<{ domain: VLANDomain | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const devicesStore = useDevicesStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.domain !== null)

function emptyForm() {
  return { name: '', description: '', source_device_id: '', auto_sync: false }
}
const form = reactive(emptyForm())

const members = ref<VLANDomainDeviceLink[]>([])
const loadingMembers = ref(false)
const addMemberDeviceId = ref('')
const memberBusyId = ref<string | null>(null)

const memberDeviceIds = computed(() => new Set(members.value.map((m) => m.physical_device_id)))
const availableToAdd = computed(() => devicesStore.all.filter((d) => !memberDeviceIds.value.has(d.id)))

function deviceLabel(d: Device): string {
  return d.system_name || d.serial_number
}
function memberDeviceLabel(deviceId: string): string {
  const d = devicesStore.all.find((x) => x.id === deviceId)
  return d ? deviceLabel(d) : deviceId
}

watch(
  () => props.domain,
  async (d) => {
    Object.assign(form, emptyForm())
    members.value = []
    if (d) {
      form.name = d.name
      form.description = d.description ?? ''
      form.source_device_id = d.source_device_id ?? ''
      form.auto_sync = d.auto_sync
      loadingMembers.value = true
      try {
        const res = await listResource<VLANDomainDeviceLink>('vlan-domain-devices', { domain_id: d.id, limit: 1000 })
        members.value = res.items
      } catch (err) {
        errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить состав домена'
      } finally {
        loadingMembers.value = false
      }
    }
  },
  { immediate: true },
)

async function addMember() {
  if (!props.domain || !addMemberDeviceId.value) return
  const deviceId = addMemberDeviceId.value
  try {
    const link = await api.post<VLANDomainDeviceLink>(`/vlan-domains/${props.domain.id}/members`, { physical_device_id: deviceId })
    members.value = [...members.value, link]
    addMemberDeviceId.value = ''
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось добавить устройство в домен'
  }
}

async function removeMember(link: VLANDomainDeviceLink) {
  memberBusyId.value = link.id
  try {
    await deleteResource('vlan-domain-devices', link.id)
    members.value = members.value.filter((m) => m.id !== link.id)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось убрать устройство из домена'
  } finally {
    memberBusyId.value = null
  }
}

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование домена.'
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description || null,
      source_device_id: form.source_device_id || null,
      auto_sync: form.auto_sync,
    }
    if (isEdit.value) await updateResource('vlan-domains', props.domain!.id, payload)
    else await createResource('vlan-domains', payload)
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить VLAN-домен'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать VLAN-домен' : 'Добавить VLAN-домен' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form class="form-grid" @submit.prevent="submit">
        <label class="field field-wide">
          <span>Наименование *</span>
          <input v-model.trim="form.name" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Устройство-источник</span>
          <select v-model="form.source_device_id">
            <option value="">— не задано (без синхронизации) —</option>
            <option v-for="d in devicesStore.all" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
          </select>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.auto_sync" type="checkbox" />
          <span>Автосинхронизация</span>
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <div v-if="isEdit" class="nested-editor field-wide">
          <div class="nested-head">
            <b>Устройства домена</b>
            <span class="hint">Все устройства домена получают набор VLAN устройства-источника при синхронизации.</span>
          </div>

          <p v-if="loadingMembers" class="loading-hint">Загрузка состава домена…</p>
          <template v-else>
            <div v-if="!members.length" class="empty">Устройства не добавлены</div>
            <div v-for="m in members" :key="m.id" class="member-row">
              <span>{{ memberDeviceLabel(m.physical_device_id) }}</span>
              <button type="button" class="icon-btn danger" :disabled="memberBusyId === m.id" aria-label="Убрать из домена" @click="removeMember(m)">
                <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
              </button>
            </div>
            <div class="add-member-row">
              <select v-model="addMemberDeviceId">
                <option value="">— выберите устройство —</option>
                <option v-for="d in availableToAdd" :key="d.id" :value="d.id">{{ deviceLabel(d) }}</option>
              </select>
              <button type="button" class="btn btn-secondary" :disabled="!addMemberDeviceId" @click="addMember">
                <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                Добавить
              </button>
            </div>
          </template>
        </div>
        <p v-else class="loading-hint field-wide">Состав домена можно настроить после первого сохранения.</p>
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
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}
.checkbox-field input {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
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
.nested-editor {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.nested-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nested-head b {
  font-size: 12.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.member-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink);
  padding: 4px 0;
}
.add-member-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  margin-top: 4px;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .add-member-row {
    grid-template-columns: 1fr;
  }
}
</style>
