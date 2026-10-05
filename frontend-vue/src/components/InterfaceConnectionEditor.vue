<script setup lang="ts">
// Блок «Подключение» в раскрытой строке порта (DeviceInterfacesEditor.vue): порт подключается к порту
// другого устройства прямо при создании/редактировании устройства — без перехода на экран
// «Подключения». Выбор в два шага (устройство → порт), как в ConnectionFormModal.vue, плюс тип физической
// линии связи и описание.
//
// Компонент только редактирует черновик (v-model: InterfaceConnectionDraft | null) и ничего не сохраняет
// и не загружает: подключение уходит на сервер вместе с портами одним PUT (см. api/deviceInterfaces.ts:
// persistDeviceInterfaces), а сторы устройств, подключений и каталог портов загружает форма устройства.
// Это нужно, потому что у нового порта ещё нет id — отдельным запросом подключение создать нельзя.
//
// Соседний порт можно выбрать только на ДРУГОМ устройстве и только из уже сохранённых портов: порт этого
// же устройства, ещё не сохранённый, не имеет id, на который можно сослаться (подключение между портами
// одного устройства создаётся на экране «Подключения»). Из списка исключены порты, уже занятые активным
// подключением, и порты, выбранные в соседних строках этой же формы; порт, выбранный в этой строке,
// остаётся доступным, чтобы подключение можно было открыть и изменить его тип или описание.
//
// Расхождение конфигурации (Управление / Передача данных / режим порта) с портом соседа показывается
// сразу — до сохранения. Сохранению оно не мешает: как и у подключения, созданного на экране
// «Подключения», расхождение отображается там со статусом «расхождение» до решения или одобрения.
import { computed } from 'vue'
import type { DeviceInterface, InterfaceConnectionDraft } from '../api/types'
import { useCatalogsStore, RU_COLLATOR } from '../stores/catalogs'
import { useConnectionsStore } from '../stores/connections'
import { useDevicesStore } from '../stores/devices'
import { connectionConfigDiffs, emptyConnectionDraft } from '../utils/interfaceConnections'
import SearchableSelect from './SearchableSelect.vue'

const props = withDefaults(
  defineProps<{
    modelValue: InterfaceConnectionDraft | null
    /** Устройство, чьи порты редактируются (null — новое): его порты в списке соседей не показываются. */
    deviceId: string | null
    /** Текущая конфигурация порта этой строки — для сравнения с портом соседа. */
    config: Pick<DeviceInterface, 'is_management' | 'is_data_transfer' | 'vlan_mode'>
    /** Порты соседей, уже выбранные в ДРУГИХ строках формы. */
    takenPeerIds?: ReadonlySet<string>
  }>(),
  { takenPeerIds: () => new Set<string>() },
)
const emit = defineEmits<{ 'update:modelValue': [value: InterfaceConnectionDraft | null] }>()

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const connectionsStore = useConnectionsStore()

const allInterfaces = computed(() => (catalogs.items['interfaces'] ?? []) as unknown as DeviceInterface[])

const deviceOptions = computed(() =>
  devicesStore.all
    .filter((d) => d.id !== props.deviceId)
    .map((d) => ({ value: d.id, label: d.system_name || d.serial_number }))
    .sort((a, b) => RU_COLLATOR.compare(a.label, b.label)),
)

const peerInterfaces = computed(() => {
  const draft = props.modelValue
  if (!draft?.peer_device_id) return []
  const occupied = connectionsStore.occupiedInterfaceIds
  return allInterfaces.value.filter(
    (i) => i.physical_device_id === draft.peer_device_id && (i.id === draft.peer_interface_id || (!occupied.has(i.id) && !props.takenPeerIds.has(i.id))),
  )
})
const portOptions = computed(() => peerInterfaces.value.map((i) => ({ value: i.id, label: i.name })))
const typeOptions = computed(() => (catalogs.items['connection-types'] ?? []).map((t) => ({ value: t.id, label: t.name })))

const peerHasNoFreePorts = computed(() => !!props.modelValue?.peer_device_id && portOptions.value.length === 0)

const configDiffs = computed(() => {
  const peer = allInterfaces.value.find((i) => i.id === props.modelValue?.peer_interface_id)
  return peer ? connectionConfigDiffs(props.config, peer) : []
})

function patch(change: Partial<InterfaceConnectionDraft>) {
  if (props.modelValue) emit('update:modelValue', { ...props.modelValue, ...change })
}
// Смена устройства-соседа сбрасывает порт: иначе в черновике остался бы порт другого устройства.
function onPeerDeviceChange(deviceId: string) {
  patch({ peer_device_id: deviceId, peer_interface_id: '' })
}
</script>

<template>
  <div class="connection-block">
    <div class="connection-head">
      <b>Подключение</b>
      <button v-if="!modelValue" type="button" class="btn btn-secondary connection-connect-btn" @click="emit('update:modelValue', emptyConnectionDraft())">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Подключить
      </button>
      <button v-else type="button" class="btn btn-secondary connection-disconnect-btn" @click="emit('update:modelValue', null)">
        <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        Отключить
      </button>
    </div>

    <div v-if="!modelValue" class="connection-empty">Порт не подключён</div>
    <template v-else>
      <div class="connection-grid">
        <label class="field connection-peer-device">
          <span>Устройство</span>
          <SearchableSelect :model-value="modelValue.peer_device_id" :options="deviceOptions" placeholder="— выберите —" @update:model-value="onPeerDeviceChange" />
        </label>
        <label class="field connection-peer-port">
          <span>Порт *</span>
          <SearchableSelect :model-value="modelValue.peer_interface_id" :options="portOptions" :disabled="!modelValue.peer_device_id" placeholder="— выберите —" @update:model-value="(v) => patch({ peer_interface_id: v })" />
        </label>
        <label class="field connection-type">
          <span>Тип физической линии связи *</span>
          <SearchableSelect :model-value="modelValue.connection_type_id" :options="typeOptions" placeholder="— выберите —" @update:model-value="(v) => patch({ connection_type_id: v })" />
        </label>
        <label class="field connection-description">
          <span>Описание</span>
          <input type="text" :value="modelValue.description" maxlength="500" @input="patch({ description: ($event.target as HTMLInputElement).value })" />
        </label>
      </div>
      <small v-if="peerHasNoFreePorts" class="connection-hint">У выбранного устройства нет свободных сохранённых портов: все заняты активными подключениями или ещё не созданы.</small>
      <div v-if="configDiffs.length" class="connection-diffs" role="status">
        <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
        <span>Конфигурация порта расходится с портом соседа — {{ configDiffs.join('; ') }}. Сохранить можно: расхождение будет отмечено на экране «Подключения».</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.connection-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.connection-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.connection-head b {
  font-size: 11.5px;
}
.connection-empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.connection-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--ink-muted);
  min-width: 0;
}
.field input[type='text'] {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.connection-hint {
  font-size: 11px;
  color: var(--ink-muted);
}
.connection-diffs {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink);
}
.connection-diffs .conflict-icon {
  flex: none;
  color: var(--status-warn);
  width: 14px;
  height: 14px;
  margin-top: 1px;
}
@media (max-width: 640px) {
  .connection-grid {
    grid-template-columns: 1fr;
  }
}
</style>
