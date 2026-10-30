<script setup lang="ts">
// Управление портами (интерфейсами) устройства прямо с экрана «Подключения» — раньше для этого
// нужно было открывать форму устройства целиком (см. ConnectionFormModal.vue/ConnectionsView.vue,
// откуда открывается эта модалка, и frontend-vue/README.md: было в «Ещё не сделано»).
//
// Переиспользует DeviceInterfacesEditor.vue как есть (та же карточная разметка портов, генератор
// по шаблону, вложенные IP, чекбоксы VLAN на порту) — здесь только загрузка/сохранение
// конкретного устройства вокруг него, вынесенные в api/deviceInterfaces.ts и api/portVlans.ts
// (используются так же DeviceFormModal.vue). Порты, занятые активным подключением, при удалении
// отклоняются бэкендом 409-ошибкой (FK-констрейнт Connection → DeviceInterface, см.
// delete_resource в backend/app/services/crud/deletion.py, sync_interfaces в crud/interfaces.py) — то же сообщение об ошибке,
// что и у остальных форм.
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { fetchDeviceInterfaceConnections, type DeviceInterfaceConnection } from '../api/deviceConnectivity'
import { loadDeviceInterfaceDraftRows, loadDeviceInterfaceGroups, persistDeviceInterfaces, validateInterfaceDraftRows } from '../api/deviceInterfaces'
import { validateInterfaceGroups } from '../utils/interfaceGroups'
import { computePortVlanOptions, loadAssignedDeviceVlanIds, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Device, DeviceInterface, InterfaceDraftRow, InterfaceGroupDraft, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { buildPortConflictNotice, computePortConflicts, snapshotPortConfigs, type PortConfig } from '../utils/portConflicts'

const props = defineProps<{ deviceId: string; deviceLabel: string }>()
const emit = defineEmits<{ close: []; saved: [deviceId: string, items: DeviceInterface[]] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const { notify } = useToast()
// Конфигурация сохранённых портов на момент открытия — по ней после сохранения определяется, что порт
// с расхождением относительно соседа сохраняется с НОВОЙ конфигурацией (см. utils/portConflicts.ts,
// то же правило, что в DeviceFormModal.vue). Неизменяемый снимок, не состояние формы.
let initialPortConfigs = new Map<string, PortConfig>()
// Подключения портов этого устройства со сведениями о соседе — с сервера: по ним после сохранения ищутся
// расхождения конфигурации с соседними портами (не по общим спискам с потолком в 1000 записей).
let savedConnections: DeviceInterfaceConnection[] = []
const interfaces = ref<InterfaceDraftRow[]>([])
// Группы портов устройства (InterfaceGroupsPanel.vue внутри DeviceInterfacesEditor.vue): грузятся
// и сохраняются вместе с портами одним атомарным PUT, иначе правка портов здесь молча отвязала бы
// порты от групп.
const interfaceGroups = ref<InterfaceGroupDraft[]>([])
// Статический список (в отличие от DeviceFormModal.vue:portVlanOptions) — эта модалка не
// редактирует "VLAN устройства", поэтому источник "уже назначенных" VLAN — то, что реально в
// БД на момент открытия, без реактивного пересчёта. См. api/portVlans.ts.
const portVlanOptions = ref<VLANDefinition[]>([])
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref<string | null>(null)

onMounted(async () => {
  // Каталоги (типы/скорости интерфейсов) почти наверняка уже загружены родительским экраном
  // (ConnectionsView.vue вызывает ensureLoaded() при монтировании), но модалка не должна на это
  // полагаться — ensureLoaded() сама не делает лишний запрос, если уже загружено или грузится.
  await Promise.all([catalogs.ensureLoaded(), vlansStore.ensureLoaded()])
  try {
    const [rows, groups, device, connections] = await Promise.all([
      loadDeviceInterfaceDraftRows(props.deviceId),
      loadDeviceInterfaceGroups(props.deviceId),
      api.get<Device>(`/resources/devices/${props.deviceId}`),
      fetchDeviceInterfaceConnections(props.deviceId),
    ])
    savedConnections = connections
    interfaces.value = rows
    interfaceGroups.value = groups
    initialPortConfigs = snapshotPortConfigs(rows)
    const [typeVlanIds, assignedVlanIds] = await Promise.all([loadDeviceTypeVlanIds(device.device_type_id), loadAssignedDeviceVlanIds(props.deviceId)])
    portVlanOptions.value = computePortVlanOptions(vlansStore.allDefinitions, typeVlanIds, assignedVlanIds)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить порты устройства'
  } finally {
    loading.value = false
  }
})

async function submit() {
  errorMessage.value = null
  // VLAN устройства известны (portVlanOptions): по ним проверяется, что VLAN подинтерфейсов портов и групп — из VLAN порта/группы.
  const deviceVlanIds = new Set(portVlanOptions.value.map((v) => v.id))
  const interfaceError =
    validateInterfaceDraftRows(interfaces.value, catalogs.protocolPortCatalog, deviceVlanIds) ??
    validateInterfaceGroups(interfaceGroups.value, catalogs.protocolPortCatalog, deviceVlanIds)
  if (interfaceError) {
    errorMessage.value = interfaceError
    return
  }
  saving.value = true
  try {
    const { items } = await persistDeviceInterfaces(props.deviceId, interfaces.value, interfaceGroups.value)
    catalogs.replaceDeviceInterfaces(props.deviceId, items)
    // Сосед — по данным сервера на момент открытия окна: подключения здесь не редактируются.
    const conflicts = computePortConflicts(interfaces.value, savedConnections)
    const notice = buildPortConflictNotice(interfaces.value, conflicts, initialPortConfigs)
    if (notice) notify(notice, 'warning')
    emit('saved', props.deviceId, items)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить порты устройства'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <!-- Teleport в body: эта модалка может открываться поверх ConnectionFormModal.vue (сама тоже
       модалка) — без Teleport получился бы вложенный position:fixed оверлей внутри оверлея
       (двойное затемнение фона) вместо чистой замены поверх экрана. Тот же приём, что
       QuickAddModal.vue, хоть и по другой причине (там — во избежание вложенного <form>). -->
  <Teleport to="body">
    <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
      <div class="modal card" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>Порты устройства «{{ deviceLabel }}»</h2>
          <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
          </button>
        </div>

        <div v-if="errorMessage" class="form-error">
          <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
          {{ errorMessage }}
        </div>

        <p v-if="loading" class="loading-hint">Загрузка портов устройства…</p>
        <DeviceInterfacesEditor
          v-else
          v-model="interfaces"
          v-model:groups="interfaceGroups"
          :type-options="catalogs.items['interface-types'] ?? []"
          :speed-options="catalogs.items['interface-speeds'] ?? []"
          :vlan-options="portVlanOptions"
          :protocol-port-catalog="catalogs.protocolPortCatalog"
          :device-id="props.deviceId"
        />

        <div class="modal-foot">
          <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
          <button type="button" class="btn btn-primary" :disabled="saving || loading" @click="submit">
            {{ saving ? 'Сохранение…' : 'Сохранить порты' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
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
  /* Фикс п.3.2: было 640px фиксированных — та же ширина, что DeviceFormModal.vue до её
     собственного фикса (см. её комментарий про clamp()). "Управлять портами устройства"
     открывается с тем же по духу содержимым (DeviceInterfacesEditor.vue), что и форма
     устройства, — should выглядеть и вести себя так же по ширине. */
  max-width: clamp(640px, 50vw, 1100px);
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 10px;
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
.loading-hint {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0 0 10px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
