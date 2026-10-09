// Запрос «показать план согласования портов» из любого места приложения (например, из уведомления после
// сохранения устройства): форма, из которой он сделан, к этому моменту уже закрыта, поэтому окно плана живёт не в ней,
// а в PortSyncPlanHost (layout/AppShell.vue) и открывается по этому запросу. Состояние общее на всё приложение — как у useToast.
import { ref } from 'vue'
import type { PortSyncScope } from '../api/portSync'

export interface PortSyncPlanRequest {
  scope: PortSyncScope
  title: string
}

const DEFAULT_TITLE = 'Согласование портов по правилам'
const request = ref<PortSyncPlanRequest | null>(null)

/**
 * @example
 * usePortSyncPlanRequest().open({ connection_ids: ['c-1', 'c-2'] }, 'Согласование после изменения VLAN')
 */
export function usePortSyncPlanRequest() {
  return {
    request,
    open(scope: PortSyncScope = {}, title: string = DEFAULT_TITLE) {
      request.value = { scope, title }
    },
    close() {
      request.value = null
    },
  }
}
