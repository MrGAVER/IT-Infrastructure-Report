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
import { computed, reactive, ref, watch, useId } from 'vue'
import { api, createResource, deleteResource, updateResource } from '../api/client'
import type { Connection, Device, DeviceStack, DeviceStackDetail, DeviceStackMemberDetail, StackMemberPreview } from '../api/types'
import { useDevicesStore } from '../stores/devices'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsStore } from '../stores/connections'
import BaseModal from './BaseModal.vue'
import SearchableSelect from './SearchableSelect.vue'
import ScrollableTableWrap from './ScrollableTableWrap.vue'
import DeviceStackVlanIpEditor from './DeviceStackVlanIpEditor.vue'
import StackMemberAddConfirmModal from './StackMemberAddConfirmModal.vue'
import DeviceFormModal from './DeviceFormModal.vue'
import ConnectionFormModal from './ConnectionFormModal.vue'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ stack: DeviceStack | null }>()
const emit = defineEmits<{ close: []; saved: [stack: DeviceStack] }>()
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const devicesStore = useDevicesStore()
const catalogs = useCatalogsStore()
const connectionsStore = useConnectionsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.stack !== null)

function emptyForm() {
  return { name: '', description: '' }
}
const form = reactive(emptyForm())

const detail = ref<DeviceStackDetail | null>(null)
// Растёт при каждой успешной загрузке состава: блок общих IP VLAN перечитывает свои данные вместе с составом стека.
const vlanReloadToken = ref(0)
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
    vlanReloadToken.value += 1
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
      // Фикс п.1 правки: "Соединение" ниже открывает ConnectionFormModal.vue, чья фильтрация
      // "какие порты уже заняты" (interfacesFor → connectionsStore.occupiedInterfaceIds) читает
      // ИМЕННО этот стор — а DevicesView.vue/DeviceStacksView.vue (откуда обычно открывают эту
      // форму) его не грузят вовсе. Без ensureLoaded() здесь список занятых портов при первом же
      // открытии "Соединение" в сессии оказался бы пустым (стор ещё ни разу не подгружался), и
      // ДАЖЕ уже существующие, не имеющие отношения к этой правке подключения не исключались бы
      // из списка доступных портов — тот же стор, что использует дашборд "Подключения".
      await connectionsStore.ensureLoaded()
      await devicesStore.ensureLoaded()
      await loadDetail(s.id)
    }
  },
  { immediate: true },
)

// Добавление участника: если у стека заданы общие настройки VLAN, устройство получит их значения — перед записью
// показываем окно с тем, что будет добавлено и заменено (GET .../members/preview ничего не пишет). Нет изменений данных
// устройства — добавляем сразу, без лишнего окна.
const pendingAdd = ref<StackMemberPreview | null>(null)
const addBusy = ref(false)

async function addMember() {
  if (!props.stack || !addMemberDeviceId.value) return
  errorMessage.value = null
  try {
    const query = `physical_device_id=${encodeURIComponent(addMemberDeviceId.value)}&position=${addMemberPosition.value}`
    const preview = await api.get<StackMemberPreview>(`/device-stacks/${props.stack.id}/members/preview?${query}`)
    // Ответ без поля changes (например, у старого сервера) трактуем как «данные не меняются».
    if (preview.changes?.length) {
      pendingAdd.value = preview
      return
    }
    await commitAddMember()
  } catch (err) {
    // Сюда же приходит понятная 409 "Устройство уже состоит в стеке «...»" и 422 про VLAN вне домена устройства.
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось добавить устройство в стек'
  }
}

async function commitAddMember() {
  if (!props.stack || !addMemberDeviceId.value) return
  addBusy.value = true
  try {
    await api.post(`/device-stacks/${props.stack.id}/members`, { physical_device_id: addMemberDeviceId.value, position: addMemberPosition.value })
    addMemberDeviceId.value = ''
    pendingAdd.value = null
    await loadDetail(props.stack.id)
    // Устройство могло получить VLAN и значения общих настроек — обновляем и общий список устройств.
    await devicesStore.reload()
  } catch (err) {
    pendingAdd.value = null
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось добавить устройство в стек'
  } finally {
    addBusy.value = false
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

/** Общая настройка применена или снята: назначения VLAN у устройств могли появиться, измениться или исчезнуть — обновляем таблицу устройств (VLAN, управляющие адреса). */
async function onSharedVlanIpApplied() {
  await devicesStore.reload()
}

async function onDeviceSaved() {
  viewingDevice.value = null
  await devicesStore.reload()
  if (props.stack) await loadDetail(props.stack.id)
}

async function onConnectionSaved(_c: Connection) {
  addingConnection.value = false
  // Фикс п.1 правки "стеки устройств": ConnectionFormModal.vue создаёт подключение через API,
  // но НЕ трогает connectionsStore сам — раньше здесь перезагружался только состав/топология
  // самого стека (loadDetail), а не этот стор. connectionsStore.occupiedInterfaceIds (список
  // занятых портов, см. ConnectionFormModal.vue:interfacesFor) и сам дашборд "Подключения"
  // (ConnectionsView.vue) читают ОДИН И ТОТ ЖЕ стор — без reload() здесь только что занятые
  // порты продолжали числиться свободными до полной перезагрузки страницы (которая одна и
  // сбрасывает stores.loaded в false), а новое подключение не появлялось на дашборде без
  // отдельного захода туда после общей перезагрузки.
  await connectionsStore.reload()
  if (props.stack) await loadDetail(props.stack.id)
}

async function submit() {
  if (readOnly.value) return
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
  <BaseModal @close="emit('close')">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ isEdit ? 'Редактировать стек устройств' : 'Добавить стек устройств' }}</h2>
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
                <ScrollableTableWrap v-else label="Устройства в стеке"
                  ><table class="member-table">
                    <thead>
                      <tr>
                        <th class="col-pos">#</th>
                        <th>Устройство</th>
                        <th>Тип</th>
                        <th class="col-actions"><span class="sr-only">Действия</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="m in detail.members" :key="m.id">
                        <td class="col-pos">{{ m.stack_position }}</td>
                        <td>{{ deviceLabel(m) }}</td>
                        <td>{{ catalogs.label('device-types', m.device_type_id) }}</td>
                        <td class="col-actions">
                          <div class="row-actions">
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
                          </div>
                        </td>
                      </tr>
                    </tbody></table
                ></ScrollableTableWrap>

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
                    Подключения между портами участников — обычные соединения (см. «Подключения»), связывающими стек считаются те, у которых оба конца
                    принадлежат его устройствам.
                  </span>
                </div>

                <div v-if="!detail.connections.length" class="empty">Соединения между участниками стека не заданы</div>
                <ScrollableTableWrap v-else label="Соединения стека"
                  ><table class="member-table">
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
                  </table></ScrollableTableWrap
                >

                <button type="button" class="btn btn-secondary" :disabled="detail.members.length < 2" @click="addingConnection = true">
                  <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                  Соединение
                </button>
                <p v-if="detail.members.length < 2" class="hint">Нужно минимум два устройства в стеке, чтобы их соединить.</p>
              </div>

              <DeviceStackVlanIpEditor
                :stack-id="props.stack!.id"
                :reload-token="vlanReloadToken"
                @applied="onSharedVlanIpApplied"
                @removed="onSharedVlanIpApplied"
              />
            </template>
          </template>
          <p v-else class="loading-hint field-wide">Состав и топологию стека можно настроить после первого сохранения.</p>
        </form>
      </fieldset>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>

    <DeviceFormModal v-if="viewingDevice" :device="viewingDevice" @close="viewingDevice = null" @saved="onDeviceSaved" />
    <StackMemberAddConfirmModal v-if="pendingAdd" :preview="pendingAdd" :busy="addBusy" @confirm="commitAddMember" @cancel="pendingAdd = null" />
    <ConnectionFormModal v-if="addingConnection" :connection="null" @close="addingConnection = false" @saved="onConnectionSaved" />
  </BaseModal>
</template>

<style scoped>
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
/* Элемент сетки формы (1fr = minmax(auto, 1fr)) по умолчанию не уже своего содержимого: широкая таблица раздвигала окно за край экрана
   вместо того, чтобы листаться внутри ScrollableTableWrap (F-10). min-width: 0 даёт ему сжиматься. */
.nested-editor {
  min-width: 0;
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
/* Ячейка остаётся табличной (не flex): иначе у <th> без текста пропадает высота строки и нижняя граница шапки
   «съезжает» вверх относительно соседних заголовков. Выравнивание кнопок — во вложенном .row-actions. */
.col-actions {
  text-align: right;
  white-space: nowrap;
}
.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
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
