// Общие настройки VLAN стека на форме устройства (DeviceFormModal.vue): блок «Общие настройки VLAN стека» показывается, только
// если устройство состоит в стеке. Пока настройка VLAN задана, IP-адрес, префикс и «Управление» этого VLAN у устройства не
// редактируются — состояние берётся у самого блока (update:state) и превращается в блокировку строк «VLAN устройства».
import { computed, ref } from 'vue'
import type { Device, DeviceStackVlans } from '../api/types'
import { useDevicesStore } from '../stores/devices'
import { useVLANsStore } from '../stores/vlans'
import { sortDeviceVlanRows } from '../utils/deviceVlans'
import { lockedVlanReasons, mergeSharedSettingsIntoDraft } from '../utils/stackVlans'
import type { DeviceDraft } from './useDeviceDraft'

export function useDeviceStackVlans(draft: DeviceDraft, device: () => Device | null) {
  const vlansStore = useVLANsStore()
  const devicesStore = useDevicesStore()

  const deviceStackId = computed(() => device()?.stack_id ?? null)
  const stackVlanState = ref<DeviceStackVlans | null>(null)
  const lockedStackVlans = computed(() => (stackVlanState.value ? lockedVlanReasons(stackVlanState.value.items, stackVlanState.value.stack_name) : {}))

  function onStackVlanState(state: DeviceStackVlans) {
    stackVlanState.value = state
  }

  // Настройка применена: сервер записал значения и этому устройству (и создал недостающие назначения) — переносим их в черновик
  // «VLAN устройства», иначе сохранение формы отправило бы устаревшие значения (сервер такую правку отклонит, 409).
  async function onStackVlanApplied(state: DeviceStackVlans) {
    const current = device()
    if (current) draft.deviceVlans.value = sortDeviceVlanRows(mergeSharedSettingsIntoDraft(draft.deviceVlans.value, state.items, current.id), vlansStore.allDefinitions)
    await devicesStore.reload()
  }

  // Настройка снята: значения на устройстве остаются (поля снова редактируются), а при «убрать и у устройств» строка исчезает.
  async function onStackVlanRemoved(info: { vlanId: string; fromDevices: boolean }) {
    if (info.fromDevices) draft.deviceVlans.value = draft.deviceVlans.value.filter((row) => row.vlan_id !== info.vlanId)
    await devicesStore.reload()
  }

  return { deviceStackId, lockedStackVlans, onStackVlanState, onStackVlanApplied, onStackVlanRemoved }
}
