<script setup lang="ts">
// Строка таблицы дашборда «Подключения»: оба конца подключения с кнопками правки/управления портами, тип, роли и статус сверки портов,
// активность и действия. Данные и обработчики — на экране (ConnectionsView.vue), строка только показывает и сообщает о действиях.
import type { Connection } from '../api/types'
import { facetsLabel, formatVlans, modeAndVlansLabel, modeLabel, roleLabel } from '../utils/portConfig'

defineProps<{ connection: Connection; canWrite: boolean; deleting: boolean }>()
const emit = defineEmits<{
  'edit-port': [side: 'source' | 'destination']
  'manage-ports': [interfaceId: string, deviceLabel: string]
  review: []
  open: []
  remove: []
}>()

/** Обе стороны подключения для строки с расхождением: порт, роль, режим, VLAN. */
function sidesOf(c: Connection) {
  return [
    { key: 'source', port: c.source_interface_name, role: c.source_port_role, mode: c.source_vlan_mode, vlans: c.source_vlans },
    { key: 'destination', port: c.destination_interface_name, role: c.destination_port_role, mode: c.destination_vlan_mode, vlans: c.destination_vlans },
  ]
}
</script>

<template>
  <tr>
    <td>
      <span class="devname">{{ connection.source_device_name }}</span>
      <span class="portname mono">
        {{ connection.source_interface_name }}
        <button
          v-if="canWrite"
          type="button"
          class="port-manage-btn"
          data-action="edit-port-source"
          aria-label="Изменить роль, режим и VLAN порта источника"
          title="Изменить роль, режим и VLAN порта"
          @click="emit('edit-port', 'source')"
        >
          <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
        </button>
        <button
          v-if="canWrite"
          type="button"
          class="port-manage-btn"
          aria-label="Управлять портами исходного устройства"
          title="Управлять портами устройства"
          @click="emit('manage-ports', connection.source_interface_id, connection.source_device_name)"
        >
          <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
        </button>
      </span>
    </td>
    <td class="link-cell">
      <svg class="icon"><use href="/icons.svg#i-network" /></svg>
    </td>
    <td>
      <span class="devname">{{ connection.destination_device_name }}</span>
      <span class="portname mono">
        {{ connection.destination_interface_name }}
        <button
          v-if="canWrite"
          type="button"
          class="port-manage-btn"
          data-action="edit-port-destination"
          aria-label="Изменить роль, режим и VLAN порта назначения"
          title="Изменить роль, режим и VLAN порта"
          @click="emit('edit-port', 'destination')"
        >
          <svg class="icon"><use href="/icons.svg#i-edit" /></svg>
        </button>
        <button
          v-if="canWrite"
          type="button"
          class="port-manage-btn"
          aria-label="Управлять портами конечного устройства"
          title="Управлять портами устройства"
          @click="emit('manage-ports', connection.destination_interface_id, connection.destination_device_name)"
        >
          <svg class="icon"><use href="/icons.svg#i-settings" /></svg>
        </button>
      </span>
    </td>
    <td>{{ connection.connection_type_name }}</td>
    <td class="roles-cell">
      <template v-if="connection.port_config_status === 'ok'">
        {{ roleLabel(connection.source_port_role) }}
        <span v-if="connection.source_vlan_mode" class="role-line config-line">{{
          modeAndVlansLabel(connection.source_vlan_mode, connection.source_vlans)
        }}</span>
      </template>
      <template v-else>
        <span v-for="side in sidesOf(connection)" :key="side.key" class="role-line">
          <span class="mono">{{ side.port }}</span>: <span :class="{ diff: connection.port_config_diff.includes('role') }">{{ roleLabel(side.role) }}</span> ·
          <span :class="{ diff: connection.port_config_diff.includes('mode') }">{{ modeLabel(side.mode) }}</span> ·
          <span :class="{ diff: connection.port_config_diff.includes('vlans') }">VLAN {{ formatVlans(side.vlans) }}</span>
        </span>
        <button
          type="button"
          class="port-badge"
          :class="connection.port_config_status"
          :aria-label="`Проверить конфигурацию портов: ${connection.source_device_name} — ${connection.destination_device_name}`"
          @click="emit('review')"
        >
          {{ connection.port_config_status === 'mismatch' ? 'Расхождение' : 'Одобрено'
          }}<template v-if="connection.port_config_diff.length"> ({{ facetsLabel(connection.port_config_diff) }})</template
          >{{ connection.port_config_status === 'mismatch' ? ' — проверить' : '' }}
        </button>
      </template>
    </td>
    <td>
      <span class="status" :class="connection.is_active ? 'on' : 'off'">
        <span class="status-dot"></span>{{ connection.is_active ? 'Активно' : 'Неактивно' }}
      </span>
    </td>
    <td>
      <div class="row-actions">
        <button type="button" :aria-label="canWrite ? 'Редактировать' : 'Просмотр'" @click="emit('open')">
          <svg class="icon"><use :href="canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
        </button>
        <button v-if="canWrite" type="button" aria-label="Удалить" :disabled="deleting" @click="emit('remove')">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </td>
  </tr>
</template>

<style scoped>
.devname {
  font-weight: 600;
  display: block;
}
.portname {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--ink-muted);
  font-size: 11.3px;
  margin-top: 2px;
}
.port-manage-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  background: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
  opacity: 0;
  transition: opacity 0.1s;
}
tr:hover .port-manage-btn {
  opacity: 1;
}
.port-manage-btn:hover {
  color: var(--brand);
  background: var(--surface-2);
}
.port-manage-btn .icon {
  width: 11px;
  height: 11px;
}
.link-cell {
  text-align: center;
  color: var(--ink-muted);
}
.link-cell .icon {
  width: 14px;
  height: 14px;
}
.roles-cell {
  color: var(--ink-muted);
  max-width: 320px;
}
.role-line {
  display: block;
  font-size: 11.8px;
}
.config-line {
  font-size: 11px;
}
.role-line .diff {
  color: var(--ink);
  font-weight: 700;
  text-decoration: underline dotted var(--status-warn);
  text-underline-offset: 2px;
}
.port-badge {
  margin-top: 5px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--surface-2);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-muted);
}
.port-badge.mismatch {
  border-color: var(--status-warn);
  background: var(--status-warn-soft);
  color: var(--ink);
}
.port-badge:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.row-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.row-actions button {
  background: none;
  border: none;
  padding: 5px;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.row-actions button:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--ink);
}
.row-actions button:disabled {
  opacity: 0.4;
}
.row-actions .icon {
  width: 14px;
  height: 14px;
  display: block;
}
</style>
