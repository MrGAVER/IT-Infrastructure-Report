<script setup lang="ts">
// Раскрытая часть строки стека на дашборде «Стеки устройств»: таблица участников и общие VLAN стека. Общие VLAN подгружаются
// отдельно (composables/useStackSharedVlans.ts), поэтому экран передаёт сюда их состояние: загрузка / ошибка / строки.
import { computed } from 'vue'
import type { StackVlansState } from '../composables/useStackSharedVlans'
import type { StackSummary } from '../utils/stackSummary'
import { formatStackValues, stackVlanStatus } from '../utils/stackVlans'
import YesNoStatus from './YesNoStatus.vue'

const props = defineProps<{ summary: StackSummary; vlans: StackVlansState | undefined }>()
const emit = defineEmits<{ retry: [] }>()

// Пока состояние не пришло, показываем «загрузка» — как и раньше на экране.
const vlanStatus = computed(() => props.vlans?.status ?? 'loading')
const vlanRows = computed(() => (props.vlans?.status === 'ready' ? props.vlans.items : []))
const vlanError = computed(() => (props.vlans?.status === 'error' ? props.vlans.message : ''))
</script>

<template>
  <div class="stack-details">
    <p v-if="!summary.members.length" class="members-empty">В стеке пока нет устройств — добавьте их в окне стека («Открыть»).</p>
    <table v-else class="members-table" :aria-label="`Состав стека «${summary.stack.name}»`">
      <thead>
        <tr>
          <th>Поз.</th>
          <th>Системное имя</th>
          <th>Серийный №</th>
          <th>Производитель / модель</th>
          <th>IP управления</th>
          <th>Здание · помещение</th>
          <th>SIEM</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in summary.members" :key="m.device.id" class="member-row">
          <td class="nowrap">{{ m.position ?? '—' }}</td>
          <td>
            <span class="clip" :title="m.name">{{ m.name }}</span>
          </td>
          <td class="mono">
            <span class="clip" :title="m.device.serial_number">{{ m.device.serial_number }}</span>
          </td>
          <td>
            <span class="clip" :title="m.model || undefined">{{ m.model || '—' }}</span>
          </td>
          <td class="mono">{{ m.device.management_ips || '—' }}</td>
          <td>
            <span class="clip" :title="m.place || undefined">{{ m.place || '—' }}</span>
          </td>
          <td class="nowrap"><YesNoStatus :value="m.device.siem_enabled" /></td>
        </tr>
      </tbody>
    </table>
    <div class="stack-vlans">
      <h4 class="stack-vlans-title">Общие VLAN стека</h4>
      <p v-if="vlanStatus === 'loading'" class="members-empty">Загрузка общих VLAN…</p>
      <p v-else-if="vlanStatus === 'error'" class="members-empty vlan-error">
        Не удалось загрузить общие VLAN: {{ vlanError }}
        <button type="button" class="btn btn-secondary" @click="emit('retry')">Повторить</button>
      </p>
      <p v-else-if="!vlanRows.length" class="members-empty">Общие VLAN не заданы — настраиваются в окне стека («Открыть»).</p>
      <ul v-else class="stack-vlan-list">
        <li v-for="v in vlanRows" :key="v.vlan_id" class="stack-vlan-item">
          <b class="vlan-id">VLAN {{ v.vlan_number }}</b>
          <span v-if="v.vlan_name" class="vlan-name">{{ v.vlan_name }}</span>
          <span class="mono vlan-values">{{ formatStackValues(v) }}</span>
          <span class="status" :class="stackVlanStatus(v).kind === 'ok' ? 'on' : 'off'"> <span class="status-dot"></span>{{ stackVlanStatus(v).text }} </span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 880px;
}
thead th {
  text-align: left;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  font-weight: 600;
  white-space: nowrap;
}
tbody td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  vertical-align: middle;
}
tbody tr:last-child > td {
  border-bottom: none;
}
.nowrap {
  white-space: nowrap;
}
.muted {
  color: var(--ink-muted);
}
.mono {
  font-family: var(--font-mono, monospace);
}
/* Длинные списки (модели, IP, места нескольких участников) не раздувают строку: одна строка с многоточием, полный текст — в title. */
.clip {
  display: block;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.members-empty {
  margin: 0;
  padding: 10px 0;
  font-size: 12px;
  color: var(--ink-muted);
}
.stack-vlans {
  margin-top: 10px;
}
.stack-vlans-title {
  margin: 0;
  padding-top: 4px;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  font-weight: 600;
}
.stack-vlan-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stack-vlan-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  font-size: 12.5px;
}
.vlan-name {
  color: var(--ink-muted);
}
.vlan-error .btn {
  margin-left: 10px;
}
.members-table {
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
}
.members-table thead th {
  padding: 7px 12px;
  background: transparent;
}
.members-table tbody td {
  padding: 8px 12px;
}
.member-row:hover > td {
  background: var(--surface-2);
}
</style>
