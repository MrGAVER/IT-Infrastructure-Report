// Управление портами выбранного устройства прямо из формы подключения, без ухода в форму устройства (DevicePortsModal.vue): какое
// из двух устройств редактируется, определяет endpoint. Кнопка «Порты» у каждой стороны доступна, только когда устройство уже выбрано
// (иначе неясно, чьи порты открывать).
import { computed, ref } from 'vue'
import type { ConnectionDraft, ConnectionEndpoint } from './useConnectionDraft'

export function useConnectionPortsDialog(draft: ConnectionDraft, refreshPortConfig: () => Promise<void>) {
  const endpoint = ref<ConnectionEndpoint | null>(null)

  const deviceId = computed(() => (endpoint.value === 'source' ? draft.form.sourceDeviceId : draft.form.destinationDeviceId))
  const deviceLabel = computed(() => (endpoint.value ? draft.endpointDeviceLabel(endpoint.value) : ''))

  function open(which: ConnectionEndpoint) {
    endpoint.value = which
  }

  function close() {
    endpoint.value = null
  }

  // После сохранения портов список интерфейсов устройства в catalogs.items['interfaces'] уже обновлён самим окном (см.
  // DevicePortsModal.vue:submit → catalogs.replaceDeviceInterfaces), поэтому списки портов пересчитаются реактивно. Остаётся сбросить
  // выбор порта, если он был удалён в окне, — иначе выбор указывал бы на id, которого больше нет в списке.
  function onSaved() {
    const { form } = draft
    if (endpoint.value === 'source' && !draft.sourceInterfaces.value.some((i) => i.id === form.source_interface_id)) form.source_interface_id = ''
    if (endpoint.value === 'destination' && !draft.destinationInterfaces.value.some((i) => i.id === form.destination_interface_id))
      form.destination_interface_id = ''
    close()
    // VLAN порта могли измениться, а ключ пересчёта сверки их не видит.
    void refreshPortConfig()
  }

  return { endpoint, deviceId, deviceLabel, open, close, onSaved }
}
