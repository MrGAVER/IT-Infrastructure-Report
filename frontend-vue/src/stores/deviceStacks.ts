// Стор стеков устройств (пункт 5 правки "создание физического устройства") — простой
// generic-ресурс, по тому же образцу, что и vlanDomains.ts. Состав/топология стека сюда не
// входят — та деталь читается отдельно, по требованию, через GET /device-stacks/{id}/detail
// (см. DeviceStackFormModal.vue), а не хранится в общем сторе всех стеков разом.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { DeviceStack } from '../api/types'

export const useDeviceStacksStore = defineStore('deviceStacks', {
  state: () => ({
    all: [] as DeviceStack[],
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async ensureLoaded() {
      if (this.loaded || this.loading) return
      await this.reload()
    },
    async reload() {
      this.loading = true
      this.error = null
      try {
        const res = await listAllResource<DeviceStack>('device-stacks')
        this.all = res.items
        this.loaded = true
        warnIfTruncated(res, 'стеков устройств')
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить стеки устройств'
      } finally {
        this.loading = false
      }
    },
  },
})
