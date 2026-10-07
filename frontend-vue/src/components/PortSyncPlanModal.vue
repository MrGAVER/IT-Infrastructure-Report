<script setup lang="ts">
// План согласования данных портов по правилам (backend/app/services/port_sync_reconcile.py): что
// будет изменено, что нельзя применить и почему, что остаётся за человеком. Ничего не меняется,
// пока пользователь не отметит «Я проверил план» и не нажмёт «Применить»: план показывается заново
// при каждом открытии окна, а применение сервер сверяет с показанным (plan_hash) — если данные
// изменились после предпросмотра, он ответит 409, и окно предложит обновить план.
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '../api/client'
import { applyPortSync, previewPortSync, type PortSyncScope } from '../api/portSync'
import type { PortSyncApplyResult, PortSyncPlan, PortSyncPlanItem } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { OUTCOME_LABELS, changeLines, optionLine, plannedTargets, summaryLine } from '../utils/portSyncRules'

const props = defineProps<{ scope: PortSyncScope; title?: string }>()
const emit = defineEmits<{ close: []; applied: [result: PortSyncApplyResult] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
const { notify } = useToast()

const plan = ref<PortSyncPlan | null>(null)
const loading = ref(false)
const applying = ref(false)
const confirmed = ref(false)
const errorMessage = ref<string | null>(null)
const stale = ref(false)

const applicable = computed(() => plan.value?.summary.applicable ?? 0)
const hiddenCount = computed(() => (plan.value ? plan.value.summary.total_items - plan.value.items.length : 0))
const canApply = computed(() => applicable.value > 0 && confirmed.value && !loading.value && !applying.value)

async function load() {
  loading.value = true
  errorMessage.value = null
  stale.value = false
  confirmed.value = false
  try {
    plan.value = await previewPortSync(props.scope)
  } catch (err) {
    plan.value = null
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось построить план согласования'
  } finally {
    loading.value = false
  }
}

async function apply() {
  if (!plan.value || !canApply.value) return
  applying.value = true
  errorMessage.value = null
  try {
    const result = await applyPortSync(props.scope, plan.value.plan_hash)
    notify(`Согласовано портов: ${result.applied.ports}`, 'success')
    emit('applied', result)
    emit('close')
  } catch (err) {
    // 409 — данные изменились после предпросмотра: показанный план больше не соответствует действительности.
    stale.value = err instanceof ApiError && err.status === 409
    confirmed.value = false
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось применить план'
  } finally {
    applying.value = false
  }
}

const targetsOf = (item: PortSyncPlanItem) => plannedTargets(item)

onMounted(load)
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" :aria-label="title ?? 'Согласование портов по правилам'">
      <div class="modal-head">
        <h2>{{ title ?? 'Согласование портов по правилам' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error" role="alert" data-error>
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        <span>{{ errorMessage }}</span>
        <button v-if="stale" type="button" class="btn btn-secondary btn-sm" data-action="refresh" @click="load">Обновить план</button>
      </div>

      <div v-if="loading" class="loading" data-loading>Строится план согласования…</div>

      <template v-else-if="plan">
        <p class="summary" data-summary>{{ summaryLine(plan.summary) }}</p>

        <p v-if="!plan.items.length" class="empty" data-empty>Нет подключений, которые нужно согласовывать.</p>

        <ul v-else class="items">
          <li v-for="item in plan.items" :key="item.connection_id" class="item" :class="item.outcome" :data-outcome="item.outcome">
            <div class="item-head">
              <span class="badge" :class="item.outcome">{{ OUTCOME_LABELS[item.outcome] }}</span>
              <span class="pair">
                <span class="mono">{{ item.source.name }}</span> ({{ item.source.device_name }}) ↔
                <span class="mono">{{ item.destination.name }}</span> ({{ item.destination.device_name }})
              </span>
            </div>
            <div v-if="item.rule" class="rule-name">Правило: «{{ item.rule.name }}»</div>

            <template v-if="item.outcome === 'auto' || item.outcome === 'blocked'">
              <div v-for="t in targetsOf(item)" :key="t.port.interface_id" class="target-block" data-target>
                <div class="target">Порт «{{ t.port.name }}» ({{ t.port.device_name }}):</div>
                <ul v-if="t.changes && (!t.blocked || item.outcome === 'blocked')" class="lines">
                  <li v-for="line in changeLines(t.changes)" :key="line">{{ line }}</li>
                </ul>
                <!-- Порту из пары, которому изменение не применится, причина показывается здесь, а не теряется: -->
                <!-- второй порт той же пары при этом применяется. -->
                <p v-if="t.blocked && item.outcome === 'auto'" class="reason bad" data-target-blocked>Не изменится: {{ t.blocked }}</p>
              </div>
            </template>

            <ul v-if="item.outcome === 'manual' && item.options.length" class="lines" data-options>
              <li v-for="option in item.options" :key="option.target">Можно применить к {{ optionLine(option, item) }}</li>
            </ul>

            <p v-if="item.reason" class="reason" :class="{ bad: item.outcome === 'blocked' }" data-reason>{{ item.reason }}</p>
            <p v-for="warning in item.warnings" :key="warning" class="warning" data-warning>⚠ {{ warning }}</p>
          </li>
        </ul>

        <p v-if="hiddenCount > 0" class="hidden-note" data-hidden>
          Показаны первые {{ plan.items.length }} из {{ plan.summary.total_items }}; применяется весь план ({{ applicable }}).
        </p>
      </template>

      <div class="modal-foot">
        <label v-if="applicable > 0 && !loading" class="confirm">
          <input v-model="confirmed" type="checkbox" data-field="confirm" />
          <span>Я проверил план и согласен изменить данные портов ({{ applicable }})</span>
        </label>
        <div class="spacer"></div>
        <button type="button" class="btn btn-secondary" @click="$emit('close')">Закрыть</button>
        <button type="button" class="btn btn-primary" data-action="apply" :disabled="!canApply" @click="apply">
          Применить{{ applicable ? ` (${applicable})` : '' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 760px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.form-error span {
  flex: 1;
}
.loading,
.empty {
  color: var(--ink-muted);
  font-size: 13px;
  padding: 18px 0;
  text-align: center;
}
.summary {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 52vh;
  overflow-y: auto;
}
.item {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px 12px;
  font-size: 12.5px;
}
.item.blocked {
  border-color: var(--status-warn);
  background: var(--status-warn-soft);
}
.item-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.badge {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-radius: var(--r-s);
  padding: 2px 7px;
  background: var(--surface-2);
  color: var(--ink-muted);
  border: 1px solid var(--border);
}
.badge.auto {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.badge.blocked {
  border-color: var(--status-warn);
  color: var(--ink);
}
.rule-name {
  margin-top: 4px;
  color: var(--ink-muted);
  font-size: 11.5px;
}
.target-block + .target-block {
  margin-top: 6px;
}
.target {
  margin-top: 6px;
  font-weight: 600;
}
.lines {
  margin: 4px 0 0;
  padding-left: 18px;
}
.reason {
  margin: 6px 0 0;
  color: var(--ink-muted);
}
.reason.bad {
  color: var(--ink);
  font-weight: 600;
}
.warning {
  margin: 6px 0 0;
  color: var(--ink);
}
.hidden-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}
.modal-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.spacer {
  flex: 1;
}
.confirm {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
.confirm input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
</style>
