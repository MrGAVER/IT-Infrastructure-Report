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
// delete_resource/sync_interfaces в backend/app/services/crud.py) — то же сообщение об ошибке,
// что и у остальных форм.
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { loadDeviceInterfaceDraftRows, persistDeviceInterfaces, validateInterfaceDraftRows } from '../api/deviceInterfaces'
import { computePortVlanOptions, loadAssignedDeviceVlanIds, loadDeviceTypeVlanIds } from '../api/portVlans'
import type { Device, DeviceInterface, InterfaceDraftRow, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import DeviceInterfacesEditor from './DeviceInterfacesEditor.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

const props = defineProps<{ deviceId: string; deviceLabel: string }>()
const emit = defineEmits<{ close: []; saved: [deviceId: string, items: DeviceInterface[]] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
const interfaces = ref<InterfaceDraftRow[]>([])
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
    const [rows, device] = await Promise.all([loadDeviceInterfaceDraftRows(props.deviceId), api.get<Device>(`/resources/devices/${props.deviceId}`)])
    interfaces.value = rows
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
  const interfaceError = validateInterfaceDraftRows(interfaces.value)
  if (interfaceError) {
    errorMessage.value = interfaceError
    return
  }
  saving.value = true
  try {
    const { items } = await persistDeviceInterfaces(props.deviceId, interfaces.value)
    catalogs.replaceDeviceInterfaces(props.deviceId, items)
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
          :type-options="catalogs.items['interface-types'] ?? []"
          :speed-options="catalogs.items['interface-speeds'] ?? []"
          :vlan-options="portVlanOptions"
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
  max-width: 640px;
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
