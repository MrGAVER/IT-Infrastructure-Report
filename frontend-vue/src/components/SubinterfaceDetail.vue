<script setup lang="ts">
// Раскрытая часть строки подинтерфейса: описание, IP-адреса и открытые порты. Как и сам редактор (InterfaceSubinterfacesEditor.vue), ничего
// не знает про API: получает строку и сообщает об изменении частичным патчем через `update` — патч применяет редактор.
import type { InterfaceIpDraftRow, SubinterfaceDraftRow, ProtocolPortCatalogEntry } from '../api/types'
import OpenPortListEditor from './OpenPortListEditor.vue'

const props = defineProps<{
  sub: SubinterfaceDraftRow
  readonly: boolean
  protocolPortCatalog: ProtocolPortCatalogEntry[]
  /** Порог сворачивания списка открытых портов (общий порог из «Настроек»); не передан — без сворачивания. */
  collapseAfter?: number
}>()
const emit = defineEmits<{ update: [patch: Partial<SubinterfaceDraftRow>] }>()

function addIp() {
  emit('update', { ips: [...props.sub.ips, { ip_address: '', prefix_length: '', purpose: '' }] })
}
function removeIp(ipIndex: number) {
  emit('update', { ips: props.sub.ips.filter((_, j) => j !== ipIndex) })
}
function updateIp(ipIndex: number, patch: Partial<InterfaceIpDraftRow>) {
  emit('update', { ips: props.sub.ips.map((ip, j) => (j === ipIndex ? { ...ip, ...patch } : ip)) })
}
</script>

<template>
  <div class="sub-detail">
    <label class="sub-field">
      <span>Описание</span>
      <input
        type="text"
        :value="sub.description"
        :disabled="readonly"
        placeholder="Необязательно"
        aria-label="Описание подинтерфейса"
        @input="emit('update', { description: ($event.target as HTMLInputElement).value })"
      />
    </label>

    <div class="sub-ips">
      <div class="sub-ips-head">
        <b>IP-адреса подинтерфейса</b>
        <button v-if="!readonly" type="button" class="btn btn-secondary" @click="addIp">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          IP-адрес
        </button>
      </div>
      <div v-if="!sub.ips.length" class="empty">IP-адреса не добавлены</div>
      <div v-for="(ip, j) in sub.ips" :key="ip.id ?? j" class="ip-row">
        <input
          type="text"
          placeholder="IP-адрес"
          aria-label="IP-адрес подинтерфейса"
          :value="ip.ip_address"
          :disabled="readonly"
          @input="updateIp(j, { ip_address: ($event.target as HTMLInputElement).value })"
        />
        <input
          type="number"
          min="0"
          max="32"
          placeholder="Префикс"
          aria-label="Префикс"
          :value="ip.prefix_length"
          :disabled="readonly"
          @input="updateIp(j, { prefix_length: ($event.target as HTMLInputElement).value })"
        />
        <input
          type="text"
          placeholder="Назначение"
          aria-label="Назначение IP-адреса"
          :value="ip.purpose"
          :disabled="readonly"
          @input="updateIp(j, { purpose: ($event.target as HTMLInputElement).value })"
        />
        <button v-if="!readonly" type="button" class="icon-btn danger" aria-label="Удалить IP подинтерфейса" @click="removeIp(j)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </div>

    <OpenPortListEditor
      :model-value="sub.open_ports"
      :catalog-entries="protocolPortCatalog"
      :collapse-after="collapseAfter"
      :readonly="readonly"
      sorted-unique
      @update:model-value="(v) => emit('update', { open_ports: v })"
    />
  </div>
</template>

<style scoped>
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 2px 0;
}
.sub-detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.sub-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
  min-width: 0;
}
.sub-field input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
}
.sub-ips {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-ips-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ip-row {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
</style>
