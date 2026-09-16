<script setup lang="ts">
// Пункт 5 правки "создание физического устройства": стек физических устройств.
//
// "Просмотр каждого устройства в стеке по отдельности" — не отдельная фича: участник стека
// это обычное PhysicalDevice, "отдельно" — это просто открыть DeviceFormModal.vue для него
// (кнопка "Просмотреть" в таблице участников ниже, вложенная модалка поверх этой же формы).
// "Просмотр... вместе" — это и есть сама эта форма в режиме редактирования: участники и
// связывающие их подключения одним экраном.
//
// Управление составом и топологией доступно только при редактировании УЖЕ СУЩЕСТВУЮЩЕГО
// стека — тот же приём, что и в VLANDomainFormModal.vue: добавление участника идёт через
// POST /device-stacks/{id}/members, которому нужен реальный id стека.
import { computed, reactive, ref, watch } from 'vue'
import { api, createResource, deleteResource, updateResource } from '../api/client'
import type { Connection, Device, DeviceStack, DeviceStackDetail, DeviceStackMemberDetail } from '../api/types'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import SearchableSelect from './SearchableSelect.vue'
import DeviceFormModal from './DeviceFormModal.vue'
import ConnectionFormModal from './ConnectionFormModal.vue'

const props = defineProps<{ stack: DeviceStack | null }>()
const emit = defineEmits<{ close: []; saved: [stack: DeviceStack] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const devicesStore = useDevicesStore()
const catalogs = useCatalogsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.stack !== null)

function emptyForm() {
  return { name: '', description: '' }
}
const form = reactive(emptyForm())

const detail = ref<DeviceStackDetail | null>(null)
const loadingDetail = ref(false)
const addMemberDeviceId = ref('')
const addMemberPosition = ref(1)
const memberBusyId = ref<string | null>(null)
const viewingDevice = ref<Device | null>(null)
const addingConnection = ref(false)

const memberDeviceIds = computed(() => new Set((detail.value?.members ?? []).map((m) => m.id)))
const availableToAdd = computed(() => devicesStore.all.filter((d) => !memberDeviceIds.value.has(d.id)))

function deviceLabel(d: { system_name: string | null; serial_number: string }): string {
  return d.system_name || d.serial_number
}

async function loadDetail(stackId: string) {
  loadingDetail.value = true
  try {
    detail.value = await api.get<DeviceStackDetail>(`/device-stacks/${stackId}/detail`)
    addMemberPosition.value = (detail.value.members.length ?? 0) + 1
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить состав стека'
  } finally {
    loadingDetail.value = false
  }
}

watch(
  () => props.stack,
  async (s) => {
    Object.assign(form, emptyForm())
    detail.value = null
    addMemberDeviceId.value = ''
    if (s) {
      form.name = s.name
      form.description = s.description ?? ''
      await devicesStore.ensureLoaded()
      await loadDetail(s.id)
    }
  },
  { immediate: true },
)

async function addMember() {
  if (!props.stack || !addMemberDeviceId.value) return
  errorMessage.value = null
  try {
    await api.post(`/device-stacks/${props.stack.id}/members`, { physical_device_id: addMemberDeviceId.value, position: addMemberPosition.value })
    addMemberDeviceId.value = ''
    await loadDetail(props.stack.id)
  } catch (err) {
    // Сюда же приходит понятная 409 "Устройство уже состоит в стеке «...»" —
    // _validate_device_stack_member_entry в backend/app/services/crud.py.
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось добавить устройство в стек'
  }
}

async function removeMember(member: DeviceStackMemberDetail) {
  if (!props.stack) return
  memberBusyId.value = member.stack_member_id
  try {
    await deleteResource('device-stack-members', member.stack_member_id)
    await loadDetail(props.stack.id)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось убрать устройство из стека'
  } finally {
    memberBusyId.value = null
  }
}

async function onDeviceSaved() {
  viewingDevice.value = null
  await devicesStore.reload()
  if (props.stack) await loadDetail(props.stack.id)
}

async function onConnectionSaved(_c: Connection) {
  addingConnection.value = false
  if (props.stack) await loadDetail(props.stack.id)
}

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование стека.'
    return
  }
  saving.value = true
  try {
    const payload = { name: form.name.trim(), description: form.description || null }
    // Возвращаем родителю сохранённую запись (а не просто факт "сохранено") — DevicesView.vue
    // использует её, чтобы после СОЗДАНИЯ сразу переключить эту же модалку в режим
    // редактирования и дать добавить участников, не открывая форму заново.
    const saved = isEdit.value
      ? await updateResource<DeviceStack>('device-stacks', props.stack!.id, payload)
      : await createResource<DeviceStack>('device-stacks', payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить стек устройств'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать стек устройств' : 'Добавить стек устройств' }}</h2>
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
        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <template v-if="isEdit">
          <p v-if="loadingDetail" class="loading-hint field-wide">Загрузка состава стека…</p>
          <template v-else-if="detail">
            <div class="nested-editor field-wide">
              <div class="nested-head">
                <b>Устройства в стеке</b>
                <span class="hint">Позиция — номер участника в стеке (как физический stack member ID на оборудовании).</span>
              </div>

              <div v-if="!detail.members.length" class="empty">Устройства не добавлены</div>
              <table v-else class="member-table">
                <thead>
                  <tr>
                    <th class="col-pos">#</th>
                    <th>Устройство</th>
                    <th>Тип</th>
                    <th class="col-actions"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in detail.members" :key="m.id">
                    <td class="col-pos">{{ m.stack_position }}</td>
                    <td>{{ deviceLabel(m) }}</td>
                    <td>{{ catalogs.label('device-types', m.device_type_id) }}</td>
                    <td class="col-actions">
                      <button type="button" class="btn btn-secondary btn-sm" @click="viewingDevice = m">Просмотреть</button>
                      <button
                        type="button"
                        class="icon-btn danger"
                        :disabled="memberBusyId === m.stack_member_id"
                        aria-label="Убрать из стека"
                        @click="removeMember(m)"
                      >
                        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div class="add-member-row">
                <SearchableSelect
                  v-model="addMemberDeviceId"
                  :options="availableToAdd.map((d) => ({ value: d.id, label: deviceLabel(d) }))"
                  placeholder="— выберите устройство —"
                />
                <input v-model.number="addMemberPosition" type="number" min="1" class="position-input" title="Позиция в стеке" />
                <button type="button" class="btn btn-secondary" :disabled="!addMemberDeviceId" @click="addMember">
                  <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                  Добавить
                </button>
              </div>
            </div>

            <div class="nested-editor field-wide">
              <div class="nested-head">
                <b>Топология стека</b>
                <span class="hint">
                  Подключения между портами участников — обычные соединения (см. «Подключения»), связывающими стек считаются те,
                  у которых оба конца принадлежат его устройствам.
                </span>
              </div>

              <div v-if="!detail.connections.length" class="empty">Соединения между участниками стека не заданы</div>
              <table v-else class="member-table">
                <thead>
                  <tr>
                    <th>Откуда</th>
                    <th>Куда</th>
                    <th>Тип</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="c in detail.connections" :key="c.id">
                    <td>{{ c.source_device_name }} · {{ c.source_interface_name }}</td>
                    <td>{{ c.destination_device_name }} · {{ c.destination_interface_name }}</td>
                    <td>{{ c.connection_type_name }}</td>
                  </tr>
                </tbody>
              </table>

              <button type="button" class="btn btn-secondary" :disabled="detail.members.length < 2" @click="addingConnection = true">
                <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                Соединение
              </button>
              <p v-if="detail.members.length < 2" class="hint">Нужно минимум два устройства в стеке, чтобы их соединить.</p>
            </div>
          </template>
        </template>
        <p v-else class="loading-hint field-wide">Состав и топологию стека можно настроить после первого сохранения.</p>
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>

    <DeviceFormModal v-if="viewingDevice" :device="viewingDevice" @close="viewingDevice = null" @saved="onDeviceSaved" />
    <ConnectionFormModal v-if="addingConnection" :connection="null" @close="addingConnection = false" @saved="onConnectionSaved" />
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
  max-width: 720px;
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
.member-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.member-table th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.member-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.member-table tr:last-child td {
  border-bottom: none;
}
.col-pos {
  width: 32px;
}
.col-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
}
.btn-sm {
  padding: 5px 9px;
  font-size: 11.5px;
}
.add-member-row {
  display: grid;
  grid-template-columns: 1fr 70px auto;
  gap: 8px;
  margin-top: 4px;
  align-items: center;
}
.position-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 6px;
  font-size: 12.5px;
  color: var(--ink);
  width: 100%;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .add-member-row {
    grid-template-columns: 1fr;
  }
}
</style>
