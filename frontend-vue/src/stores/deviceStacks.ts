// Стор стеков устройств (пункт 5 правки "создание физического устройства") — простой
// generic-ресурс, по тому же образцу, что и vlanDomains.ts. Состав/топология стека сюда не
// входят — та деталь читается отдельно, по требованию, через GET /device-stacks/{id}/detail
// (см. DeviceStackFormModal.vue), а не хранится в общем сторе всех стеков разом.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { DeviceStack } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// B-02: ответ на более ранний reload() не должен затереть более поздний (см. utils/latestRequest.ts).
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
      if (this.loaded || this.loading) return
      await this.reload()
    },
    async reload() {
      const isLatest = latest.begin()
      this.loading = true
      this.error = null
      try {
        const res = await listAllResource<DeviceStack>('device-stacks')
        if (!isLatest()) return // устаревший ответ: finally ничего не тронет
        this.all = res.items
        this.total = res.total
        this.truncated = res.truncated === true
        this.loaded = true
        warnIfTruncated(res, 'стеков устройств')
      } catch (e) {
        if (isLatest()) this.error = e instanceof Error ? e.message : 'Не удалось загрузить стеки устройств'
      } finally {
        if (isLatest()) this.loading = false
      }
    },
  },
})
