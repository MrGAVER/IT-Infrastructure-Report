// Стор стеков устройств (пункт 5 правки "создание физического устройства") — простой
// generic-ресурс, по тому же образцу, что и vlanDomains.ts. Состав/топология стека сюда не
// входят — та деталь читается отдельно, по требованию, через GET /device-stacks/{id}/detail
// (см. DeviceStackFormModal.vue), а не хранится в общем сторе всех стеков разом.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { DeviceStack } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'
import { useDevicesStore } from './devices'

// Ответ на более ранний reload() не должен затереть более поздний (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useDeviceStacksStore = defineStore('deviceStacks', {
  state: () => ({
    all: [] as DeviceStack[],
    total: 0,
    truncated: false,
    // Загружено не всё (потолок listAllResource): экраны, показывающие этот список целиком, выводят постоянное DataLoadNotice,
    // а не только исчезающее через 10 с предупреждение warnIfTruncated.
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async ensureLoaded() {
      await latest.ensure(this, () => this.reload())
    },
    async reload() {
      await latest.run(this, {
        fetch: () => listAllResource<DeviceStack>('device-stacks'),
        apply: (res) => {
          this.all = res.items
          this.total = res.total
          this.truncated = res.truncated === true
          this.loaded = true
          warnIfTruncated(res, 'стеков устройств')
        },
        errorMessage: 'Не удалось загрузить стеки устройств',
      })
    },
    /** Стек создан, изменён или потерял/получил участников: состав стека читается с устройств (stack_id/stack_position в
     * реестре устройств), поэтому перечитываются оба списка. Вызывается там, где стеком управляют (окно стека в
     * «Инвентаризации устройств» и в «Стеках устройств»): ensureLoaded() уже загруженный стор не перечитывает, и без этого
     * дашборд «Стеки устройств» показывал бы прежние данные до перезагрузки страницы. */
    async reloadWithDevices() {
      await Promise.all([this.reload(), useDevicesStore().reload()])
    },
  },
})
