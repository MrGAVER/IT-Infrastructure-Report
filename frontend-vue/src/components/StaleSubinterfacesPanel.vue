<script setup lang="ts">
// Панель диагностики «подинтерфейсы на VLAN, не разрешённом устройству» (экран VLAN). VLAN, снятый с устройства, убранный из его
// типа или перенесённый в другой домен, оставляет подинтерфейсы порта на себе: система их не удаляет — на них IP-адреса и открытые
// порты, — а форма устройства потребует выбрать другой VLAN или удалить подинтерфейс. Панель показывает все такие случаи по
// реестру сразу и ведёт в форму нужного устройства (событие open-device). Если проблем нет — панель не занимает места на экране.
import { computed, onMounted, ref } from 'vue'
import { fetchStaleSubinterfaces, groupStaleByDevice, staleVlanText } from '../api/staleSubinterfaces'
import type { StaleSubinterfacesReport } from '../api/staleSubinterfaces'

const emit = defineEmits<{ 'open-device': [deviceId: string] }>()

const report = ref<StaleSubinterfacesReport | null>(null)
const loading = ref(false)
const errorText = ref('')

const groups = computed(() => groupStaleByDevice(report.value?.subinterfaces ?? []))

async function reload() {
  loading.value = true
  errorText.value = ''
  try {
    report.value = await fetchStaleSubinterfaces()
  } catch (err) {
    // Диагностика, которая молча не сработала, хуже отсутствующей: показываем причину и даём повторить.
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(reload)
defineExpose({ reload })
</script>

<template>
  <div v-if="errorText" class="stale-panel card stale-error" role="alert">
    <span>Не удалось проверить подинтерфейсы на недоступных VLAN: {{ errorText }}</span>
    <button type="button" class="btn btn-secondary" :disabled="loading" @click="reload">Повторить</button>
  </div>

  <div v-else-if="report && !report.ok" class="stale-panel card" role="region" aria-label="Подинтерфейсы на недоступных VLAN">
    <div class="stale-head">
      <div>
        <b>Подинтерфейсы на VLAN, не разрешённом устройству: {{ report.total }}</b>
        <div class="hint">
          VLAN сняли с устройства, убрали из его типа или перенесли в другой домен. Подинтерфейсы не удаляются сами — на них IP-адреса и открытые порты.
          Откройте устройство и перенесите подинтерфейс на другой VLAN или удалите его: пока этого не сделано, форма устройства не сохранится.
        </div>
      </div>
      <button type="button" class="btn btn-secondary" :disabled="loading" @click="reload">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Проверить снова
      </button>
    </div>

    <div v-for="group in groups" :key="group.device_id" class="stale-device">
      <div class="stale-device-head">
        <b>{{ group.device_name }}</b>
        <button type="button" class="btn btn-secondary" @click="emit('open-device', group.device_id)">Открыть устройство</button>
      </div>
      <ul class="stale-list">
        <li v-for="item in group.items" :key="item.subinterface_id">
          <span class="stale-port">{{ item.port_name }}</span>
          <span class="stale-sub">{{ item.subinterface_name }}</span>
          <span class="stale-vlan">{{ staleVlanText(item) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.stale-panel {
  padding: 14px 16px;
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-left: 3px solid var(--status-warn);
}
.stale-error {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  color: var(--status-crit);
  border-left-color: var(--status-crit);
}
.stale-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.stale-head b {
  font-size: 13px;
}
.hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin-top: 2px;
  max-width: 70ch;
}
.stale-device {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}
.stale-device-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
}
.stale-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stale-list li {
  display: grid;
  grid-template-columns: 1fr 1.2fr 1.6fr;
  gap: 8px;
  font-size: 12px;
}
.stale-port {
  color: var(--ink-muted);
}
.stale-vlan {
  color: var(--status-crit);
}

@media (max-width: 720px) {
  .stale-head,
  .stale-error {
    flex-direction: column;
    align-items: stretch;
  }
  .stale-list li {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>
