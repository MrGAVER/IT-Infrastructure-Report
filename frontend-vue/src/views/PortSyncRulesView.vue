<script setup lang="ts">
// Правила автоматического согласования данных порта с портом на другом конце подключения (роль,
// режим, VLAN). Здесь правила создаются, меняются (в том числе стандартные), включаются, сбрасываются
// к исходному виду и упорядочиваются: проверка идёт сверху вниз, решает первое подходящее. Сами
// правила проверяет и применяет сервер (backend/app/services/port_sync_*.py); «Что сделает» и
// «Согласовать по правилам» открывают план — ничего не меняется без подтверждения.
import { onMounted, ref } from 'vue'
import PortSyncPlanModal from '../components/PortSyncPlanModal.vue'
import PortSyncRuleFormModal from '../components/PortSyncRuleFormModal.vue'
import StatCard from '../components/StatCard.vue'
import type { PortSyncRule } from '../api/types'
import type { PortSyncScope } from '../api/portSync'
import { useToast } from '../composables/useToast'
import { usePortSyncRulesStore } from '../stores/portSyncRules'
import { useAuthStore } from '../stores/auth'
import { actionLabel, describeRule } from '../utils/portSyncRules'

const store = usePortSyncRulesStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const formOpen = ref(false)
const editing = ref<PortSyncRule | null>(null)
const planScope = ref<PortSyncScope | null>(null)
const planTitle = ref<string | undefined>(undefined)
const busyId = ref<string | null>(null)

onMounted(() => store.load())

function openCreate() {
  editing.value = null
  formOpen.value = true
}

function openEdit(rule: PortSyncRule) {
  editing.value = rule
  formOpen.value = true
}

function onSaved(rule: PortSyncRule) {
  formOpen.value = false
  notify(editing.value ? `Правило «${rule.name}» сохранено` : `Правило «${rule.name}» создано`, 'success')
}

/** Выполняет операцию над одним правилом: блокирует его кнопки и показывает ошибку тостом. */
async function run(rule: PortSyncRule, action: () => Promise<unknown>) {
  busyId.value = rule.id
  try {
    await action()
  } catch (err) {
    notifyError(err)
  } finally {
    busyId.value = null
  }
}

const toggle = (rule: PortSyncRule) => run(rule, () => store.toggle(rule.id))
const move = (rule: PortSyncRule, delta: -1 | 1) => run(rule, () => store.move(rule.id, delta))

function reset(rule: PortSyncRule) {
  if (!confirm(`Вернуть стандартное правило «${rule.name}» к исходному виду? Ваши изменения в нём (условия, действие, порядок, «включено») будут потеряны.`))
    return
  return run(rule, async () => {
    await store.reset(rule.id)
    notify('Правило возвращено к исходному виду', 'success')
  })
}

function remove(rule: PortSyncRule) {
  if (!confirm(`Удалить правило «${rule.name}»?`)) return
  return run(rule, async () => {
    await store.remove(rule.id)
    notify('Правило удалено', 'success')
  })
}

function showPlan(scope: PortSyncScope, title?: string) {
  planScope.value = scope
  planTitle.value = title
}
</script>

<template>
  <div class="rules-view">
    <div class="stat-row">
      <StatCard :value="store.rules.length" label="Правил" />
      <StatCard :value="store.enabledCount" label="Включено" />
      <StatCard :value="store.rules.filter((r) => r.builtin).length" label="Стандартных" />
      <StatCard :value="store.rules.filter((r) => r.builtin && r.modified).length" label="Стандартных изменено" tone="warn" />
    </div>

    <p class="intro">
      Правила решают, как согласовать данные порта (роль, режим, VLAN) с портом на другом конце подключения. Проверка идёт сверху вниз, решает первое подходящее
      правило. Автоматические правила ничего не меняют сами: сначала показывается план, и только после подтверждения изменения записываются.
    </p>

    <div class="toolbar">
      <button v-if="auth.canWrite" class="btn btn-primary" data-action="create" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Новое правило
      </button>
      <button class="btn btn-secondary" data-action="plan-all" @click="showPlan({}, 'Согласование портов по правилам')">Согласовать по правилам…</button>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="store.loading" @click="store.load()">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
    </div>

    <div class="table-card card">
      <div v-if="store.error" class="error-banner">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ store.error }}
      </div>
      <div v-else-if="store.loading && !store.loaded" class="loading-banner">Загрузка правил…</div>
      <ol v-else class="rules" data-rules>
        <li v-for="(rule, index) in store.rules" :key="rule.id" class="rule" :class="{ off: !rule.enabled }" :data-rule="rule.code ?? rule.id">
          <div class="order">{{ index + 1 }}</div>
          <div class="body">
            <div class="title-row">
              <span class="name">{{ rule.name }}</span>
              <span v-if="rule.builtin" class="tag" data-tag="builtin">Стандартное</span>
              <span v-if="rule.modified" class="tag warn" data-tag="modified">Изменено</span>
              <span class="tag action" :class="rule.action" data-tag="action">{{ actionLabel(rule.action) }}</span>
              <span v-if="!rule.enabled" class="tag muted" data-tag="off">Отключено</span>
            </div>
            <p class="sentence" data-sentence>{{ describeRule(rule) }}</p>
            <p v-if="rule.description" class="description">{{ rule.description }}</p>
          </div>
          <div class="controls">
            <label class="switch" :title="rule.enabled ? 'Отключить правило' : 'Включить правило'">
              <input type="checkbox" :checked="rule.enabled" :disabled="busyId === rule.id" data-action="toggle" @change="toggle(rule)" />
              <span>{{ rule.enabled ? 'Вкл' : 'Выкл' }}</span>
            </label>
            <div class="buttons">
              <button
                v-if="auth.canWrite"
                type="button"
                class="icon-btn"
                aria-label="Выше"
                title="Проверять раньше"
                data-action="up"
                :disabled="busyId === rule.id || index === 0"
                @click="move(rule, -1)"
              >
                ↑
              </button>
              <button
                v-if="auth.canWrite"
                type="button"
                class="icon-btn"
                aria-label="Ниже"
                title="Проверять позже"
                data-action="down"
                :disabled="busyId === rule.id || index === store.rules.length - 1"
                @click="move(rule, 1)"
              >
                ↓
              </button>
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                data-action="preview"
                @click="showPlan({ rule_id: rule.id }, `Что сделает правило «${rule.name}»`)"
              >
                Что сделает
              </button>
              <button type="button" class="btn btn-secondary btn-sm" data-action="edit" @click="openEdit(rule)">
                {{ auth.canWrite ? 'Изменить' : 'Просмотр' }}
              </button>
              <button
                v-if="auth.canWrite && rule.builtin && rule.modified"
                type="button"
                class="btn btn-secondary btn-sm"
                data-action="reset"
                :disabled="busyId === rule.id"
                @click="reset(rule)"
              >
                Сбросить
              </button>
              <button
                v-if="auth.canWrite && !rule.builtin"
                type="button"
                class="btn btn-secondary btn-sm danger"
                data-action="delete"
                :disabled="busyId === rule.id"
                @click="remove(rule)"
              >
                Удалить
              </button>
            </div>
          </div>
        </li>
        <li v-if="!store.rules.length" class="empty-row" data-empty>Правил нет.</li>
      </ol>
    </div>

    <PortSyncRuleFormModal v-if="formOpen" :rule="editing" @close="formOpen = false" @saved="onSaved" />
    <PortSyncPlanModal v-if="planScope" :scope="planScope" :title="planTitle" @close="planScope = null" />
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.intro {
  margin: 0 0 14px;
  font-size: 12.5px;
  color: var(--ink-muted);
  max-width: 880px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
}
.spacer {
  flex: 1;
}
.rules {
  list-style: none;
  margin: 0;
  padding: 0;
}
.rule {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.rule:last-child {
  border-bottom: none;
}
.rule.off .body {
  opacity: 0.6;
}
.order {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--ink-muted);
  font-size: 11.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.name {
  font-weight: 600;
  font-size: 13.5px;
}
.tag {
  font-size: 10.5px;
  font-weight: 700;
  border-radius: 20px;
  padding: 2px 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--ink-muted);
}
.tag.warn {
  background: var(--status-warn-soft);
  border-color: var(--status-warn);
  color: var(--ink);
}
.tag.action.auto {
  background: var(--brand-soft);
  border-color: var(--brand);
  color: var(--brand-ink);
}
.tag.muted {
  opacity: 0.8;
}
.sentence {
  margin: 6px 0 0;
  font-size: 12.5px;
}
.description {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}
.controls {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}
.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-muted);
}
.switch input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.btn-sm {
  padding: 5px 10px;
  font-size: 11.5px;
}
.danger {
  color: var(--status-crit);
}
.empty-row {
  text-align: center;
  color: var(--ink-muted);
  padding: 26px 14px;
}
.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px;
  color: var(--status-crit);
  font-size: 13px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .rule {
    grid-template-columns: 34px 1fr;
  }
  .controls {
    grid-column: 1 / -1;
    align-items: flex-start;
  }
}
</style>
