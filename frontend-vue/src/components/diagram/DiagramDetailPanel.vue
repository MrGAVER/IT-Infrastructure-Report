<script setup lang="ts">
// Панель деталей узла/ребра по клику (раздел 11 ТЗ): "серийный номер, системное имя, список
// IP — для узла; порты и список VLAN — для ребра. Основной canvas остаётся читаемым (не
// перегружен текстом на каждом узле), полные данные — по выделению."
import { computed } from 'vue'
import type { DiagramSelection } from '../../stores/diagram'

const props = defineProps<{ selection: DiagramSelection }>()
const emit = defineEmits<{ close: []; 'expand-group': [groupKey: string] }>()

const node = computed(() => (props.selection?.kind === 'node' ? props.selection.node : null))
const edge = computed(() => (props.selection?.kind === 'edge' ? props.selection.edge : null))

function groupKeyFromNodeId(id: string): string {
  return id.startsWith('group:') ? id.slice('group:'.length) : id
}
</script>

<template>
  <aside v-if="selection" class="detail-panel card">
    <div class="panel-head">
      <span class="panel-title">{{ node ? (node.type === 'group' ? 'Группа' : 'Устройство') : 'Подключение' }}</span>
      <button class="icon-btn" type="button" aria-label="Закрыть" @click="emit('close')">
        <svg class="icon"><use href="/icons.svg#i-x" /></svg>
      </button>
    </div>

    <template v-if="node && node.type === 'device'">
      <div class="row"><span class="k">Метка</span><span class="v">{{ node.label }}</span></div>
      <div class="row"><span class="k">Серийный номер</span><span class="v mono">{{ node.serial_number || '—' }}</span></div>
      <div class="row"><span class="k">Системное имя</span><span class="v mono">{{ node.system_name || '—' }}</span></div>
      <div class="row" v-if="node.manufacturer"><span class="k">Производитель</span><span class="v">{{ node.manufacturer }}</span></div>
      <div class="row" v-if="node.model"><span class="k">Модель</span><span class="v">{{ node.model }}</span></div>
      <div class="ip-section">
        <span class="k">IP-адреса</span>
        <p v-if="!node.ip_addresses.length" class="empty">Нет IP-адресов.</p>
        <ul v-else class="ip-list">
          <li v-for="(ip, i) in node.ip_addresses" :key="i">
            <span class="mono">{{ ip.address }}</span>
            <span v-if="ip.is_management" class="badge mgmt">упр.</span>
            <span v-if="ip.purpose" class="ip-purpose">{{ ip.purpose }}</span>
          </li>
        </ul>
      </div>
    </template>

    <template v-else-if="node && node.type === 'group'">
      <div class="row"><span class="k">Название</span><span class="v">{{ node.label }}</span></div>
      <div class="row"><span class="k">Устройств в группе</span><span class="v">{{ node.device_count }}</span></div>
      <button class="btn btn-secondary expand-btn" type="button" @click="emit('expand-group', groupKeyFromNodeId(node.id))">
        Развернуть группу
      </button>
    </template>

    <template v-else-if="edge">
      <div class="row"><span class="k">Тип подключения</span><span class="v">{{ edge.connection_type || '—' }}</span></div>
      <div class="row">
        <span class="k">Статус</span>
        <span class="status" :class="edge.is_active ? 'on' : 'off'"><span class="status-dot"></span>{{ edge.is_active ? 'активно' : 'неактивно' }}</span>
      </div>
      <div class="row"><span class="k">Порт источника</span><span class="v mono">{{ edge.source_interface?.name ?? '—' }}</span></div>
      <div class="row"><span class="k">Порт назначения</span><span class="v mono">{{ edge.target_interface?.name ?? '—' }}</span></div>
      <div class="ip-section">
        <span class="k">VLAN на подключении</span>
        <p v-if="!edge.vlans.length" class="empty">VLAN не заданы.</p>
        <ul v-else class="ip-list">
          <li v-for="v in edge.vlans" :key="v.id"><span class="mono">VLAN {{ v.vlan_id }}</span> {{ v.name }}</li>
        </ul>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.detail-panel {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 280px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
  padding: 12px 14px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.panel-title {
  font-weight: 700;
  font-size: 13px;
}
.row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}
.k {
  color: var(--ink-muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.v {
  color: var(--ink);
}
.ip-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.ip-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ip-list li {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ip-purpose {
  color: var(--ink-muted);
  font-size: 11px;
}
.badge {
  font-size: 9.5px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 20px;
  text-transform: uppercase;
}
.badge.mgmt {
  color: var(--brand);
  border: 1px solid var(--brand);
}
.empty {
  color: var(--ink-muted);
  font-size: 11.5px;
  font-style: italic;
  margin: 0;
}
.expand-btn {
  align-self: flex-start;
}
</style>
