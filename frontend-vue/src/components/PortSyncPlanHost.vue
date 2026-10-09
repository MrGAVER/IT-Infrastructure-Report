<script setup lang="ts">
// Окно плана согласования портов, открываемое по запросу из любого места приложения (см. usePortSyncPlanRequest).
// После применения плана перечитываются таблица и общий кэш подключений — так же, как после согласования на самой странице.
import PortSyncPlanModal from './PortSyncPlanModal.vue'
import { usePortSyncPlanRequest } from '../composables/usePortSyncPlanRequest'
import { useToast } from '../composables/useToast'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'

const { request, close } = usePortSyncPlanRequest()
const { notifyError } = useToast()
const dashboard = useConnectionsDashboardStore()

async function onApplied() {
  try {
    await dashboard.refreshAfterChange()
  } catch (err) {
    notifyError(err) // изменения уже применены; без этого устаревшая таблица осталась бы без объяснения
  }
}
</script>

<template>
  <PortSyncPlanModal v-if="request" :scope="request.scope" :title="request.title" @close="close" @applied="onApplied" />
</template>
