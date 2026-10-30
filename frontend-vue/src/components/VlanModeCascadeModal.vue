<script setup lang="ts">
// Окно подтверждения каскадной смены режима порта (access/trunk): показывает ВСЁ, что изменится —
// группы, порты, VLAN, которые будут сняты, — и предупреждения о последствиях. Применение требует
// явной отметки «Я ознакомился с последствиями». Сам план считает сервер
// (backend/app/services/vlan_mode_cascade.py), здесь он только отображается.
import { computed, ref, watch } from 'vue'
import type { CascadeGroupChange, CascadePortChange, VlanModeCascadePlan } from '../api/vlanModeCascade'
import { modeLabel } from '../utils/vlanModeCascade'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

const props = defineProps<{
  plan: VlanModeCascadePlan
  applying: boolean
  /** Порт, с которого начинается смена, и его устройство: «b1» (CAS-GB). */
  portLabel: string
}>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const acknowledged = ref(false)
// Новый план (например, после 409 и повторного предпросмотра) требует нового подтверждения.
watch(
  () => props.plan.hash,
  () => (acknowledged.value = false),
)

const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => {
  if (!props.applying) emit('cancel')
})

const target = computed(() => modeLabel(props.plan.target_mode))

interface DeviceBlock {
  id: string
  name: string
  deferred: boolean
  groups: CascadeGroupChange[]
  ports: CascadePortChange[]
}

const blocks = computed<DeviceBlock[]>(() =>
  props.plan.devices.map((device) => ({
    id: device.id,
    name: device.name,
    deferred: device.deferred,
    groups: props.plan.groups.filter((g) => g.device_id === device.id),
    ports: props.plan.ports.filter((p) => p.device_id === device.id),
  })),
)

function vlansText(list: { vlan_id: number | null; name: string }[]): string {
  return list.map((v) => `${v.vlan_id ?? '?'}${v.name ? ` «${v.name}»` : ''}`).join(', ')
}

/** «1 порт», «2 порта», «5 портов» — русское склонение по числу. */
function plural(count: number, one: string, few: string, many: string): string {
  const lastTwo = count % 100
  const last = count % 10
  const word = lastTwo >= 11 && lastTwo <= 14 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many
  return `${count} ${word}`
}
const portsText = (count: number) => plural(count, 'порт', 'порта', 'портов')
</script>

<template>
  <div class="overlay cascade-overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="cascade-modal card" role="dialog" aria-modal="true" aria-labelledby="cascade-title">
      <div class="cascade-head">
        <h3 id="cascade-title">Сменить режим порта на {{ target }} у связанных портов</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" :disabled="applying" @click="emit('cancel')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <p class="cascade-desc">
        Режим порта должен совпадать у обеих сторон подключения. Чтобы после смены режима порта {{ portLabel }} на {{ target }} не осталось расхождений, режим
        {{ target }} будет установлен у всех связанных портов. Всего изменится: портов — <b>{{ plan.totals.ports }}</b
        >, устройств — <b>{{ plan.totals.devices }}</b
        ><template v-if="plan.totals.groups"
          >, групп — <b>{{ plan.totals.groups }}</b></template
        >.
      </p>

      <ul v-if="plan.warnings.length" class="cascade-warnings" aria-label="Последствия">
        <li v-for="w in plan.warnings" :key="w.code" :class="['cascade-warning', w.severity]" :data-code="w.code">
          <span class="cascade-warning-tag">{{ w.severity === 'warning' ? 'Внимание' : 'К сведению' }}</span>
          {{ w.text }}
        </li>
      </ul>

      <div class="cascade-list" aria-label="Что изменится">
        <section v-for="block in blocks" :key="block.id" class="cascade-device">
          <header>
            <b>{{ block.name }}</b>
            <span :class="['cascade-badge', block.deferred ? 'deferred' : 'immediate']">
              {{ block.deferred ? 'в форме — сохранится с формой' : 'применится сразу' }}
            </span>
          </header>
          <ul>
            <li v-for="g in block.groups" :key="g.id" class="cascade-item">
              <span class="cascade-item-title">Группа «{{ g.name }}» — {{ portsText(g.ports.length) }}</span>
              <span class="cascade-item-mode">{{ modeLabel(g.from_mode) }} → {{ modeLabel(g.to_mode) }}</span>
              <span class="cascade-item-ports">{{ g.ports.map((p) => p.name).join(', ') }}</span>
              <span v-if="g.dropped_vlans.length" class="cascade-item-vlans">
                VLAN группы: останется {{ vlansText(g.vlans_after) }}; будут сняты: {{ vlansText(g.dropped_vlans) }}
              </span>
            </li>
            <li v-for="p in block.ports" :key="p.id" class="cascade-item">
              <span class="cascade-item-title">Порт «{{ p.name }}»</span>
              <span class="cascade-item-mode">{{ modeLabel(p.from_mode) }} → {{ modeLabel(p.to_mode) }}</span>
              <span v-if="p.dropped_vlans.length" class="cascade-item-vlans">
                VLAN: останется {{ vlansText(p.vlans_after) }}; будут сняты: {{ vlansText(p.dropped_vlans) }}
              </span>
            </li>
          </ul>
        </section>
      </div>

      <label class="cascade-ack">
        <input v-model="acknowledged" type="checkbox" :disabled="applying" />
        Я ознакомился с последствиями
      </label>

      <div class="cascade-actions">
        <button type="button" class="btn btn-secondary" :disabled="applying" @click="emit('cancel')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="applying || !acknowledged" @click="emit('confirm')">
          {{ applying ? 'Применение…' : `Установить ${target} (портов: ${plan.totals.ports})` }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Выше окна расхождения (.overlay там z-index 70), поверх которого открывается это окно. */
.cascade-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 80;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.cascade-modal {
  width: 100%;
  max-width: 640px;
  padding: 18px 20px 16px;
}
.cascade-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.cascade-head h3 {
  font-family: var(--font-display);
  font-size: 14.5px;
  margin: 0;
}
.cascade-desc {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0 0 12px;
}
.cascade-warnings {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cascade-warning {
  font-size: 12.5px;
  line-height: 1.45;
  padding: 8px 10px;
  border-radius: var(--r-m);
  border: 1px solid var(--border);
  color: var(--ink);
}
.cascade-warning.warning {
  background: var(--status-warn-soft);
  border-color: var(--status-warn);
}
.cascade-warning-tag {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-right: 6px;
  color: var(--ink-muted);
}
.cascade-warning.warning .cascade-warning-tag {
  color: var(--status-warn);
}
.cascade-list {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 8px 10px;
  margin-bottom: 12px;
}
.cascade-device + .cascade-device {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.cascade-device header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12.5px;
  margin-bottom: 4px;
}
.cascade-badge {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--ink-muted);
}
.cascade-badge.immediate {
  color: var(--status-warn);
  border-color: var(--status-warn);
}
.cascade-badge.deferred {
  color: var(--status-ok);
  border-color: var(--status-ok);
}
.cascade-device ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.cascade-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 12px;
  font-size: 12px;
  padding: 3px 0;
}
.cascade-item-title {
  color: var(--ink);
}
.cascade-item-mode {
  font-family: var(--font-mono);
  color: var(--ink-muted);
  white-space: nowrap;
}
.cascade-item-ports,
.cascade-item-vlans {
  grid-column: 1 / -1;
  color: var(--ink-muted);
  font-size: 11.5px;
}
.cascade-item-vlans {
  color: var(--status-warn);
}
.cascade-ack {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  margin-bottom: 12px;
  cursor: pointer;
}
.cascade-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
