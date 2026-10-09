<script setup lang="ts">
// Создание и редактирование правила автоматического согласования данных порта (в том числе
// стандартного). Правило — шаблон над парой «порт ← соседний порт»: условия на каждый порт (роль,
// режим, состояние VLAN), отношение между ними, действие и то, что порт берёт у соседа. Под формой —
// правило одним предложением (utils/portSyncRules.describeRule): так видно, что именно получилось,
// ещё до сохранения. Проверку выполняет сервер; клиентская (validateRuleDraft) — только чтобы не
// отправлять заведомо неверное.
import { computed, reactive, ref, watch } from 'vue'
import type { PortSyncRule } from '../api/types'
import { usePortSyncRulesStore } from '../stores/portSyncRules'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import {
  ACTION_OPTIONS,
  MODE_CONDITION_OPTIONS,
  RELATION_OPTIONS,
  ROLE_CONDITION_OPTIONS,
  VLAN_CONDITION_OPTIONS,
  VLAN_POLICY_OPTIONS,
  describeRule,
  draftFromRule,
  emptyRuleDraft,
  payloadFromDraft,
  validateRuleDraft,
} from '../utils/portSyncRules'

const props = defineProps<{ rule: PortSyncRule | null }>()
const emit = defineEmits<{ close: []; saved: [rule: PortSyncRule] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const store = usePortSyncRulesStore()
const isEdit = computed(() => props.rule !== null)
const form = reactive(props.rule ? draftFromRule(props.rule) : emptyRuleDraft())
const saving = ref(false)
const errorMessage = ref<string | null>(null)

const actionHint = computed(() => ACTION_OPTIONS.find((o) => o.value === form.action)?.hint ?? '')
const sentence = computed(() => describeRule(form))
// Подсказка о том, что направление определяют условия: у «Автоматически» правило, подходящее обоим
// портам пары, сервер не применит — оно уйдёт на ручное решение.
// Исключение — политика VLAN «объединить»: она симметрична по замыслу, оба порта получают одно и то же.
const isUnion = computed(() => form.apply.vlans === 'union')
// «Все VLAN» — состояние устройства порта, а не набор номеров соседа: подсказка объясняет, что именно будет назначено.
const isAllVlans = computed(() => form.apply.vlans === 'all')
const symmetricHint = computed(() => form.action === 'auto' && !isUnion.value && JSON.stringify(form.target) === JSON.stringify(form.source))
// Роль и режим порт «берёт» у соседа — в одну сторону, поэтому с «объединить» они не сочетаются.
watch(isUnion, (union) => {
  if (union) {
    form.apply.role = false
    form.apply.mode = false
  }
})

async function submit() {
  errorMessage.value = validateRuleDraft(form)
  if (errorMessage.value) return
  saving.value = true
  try {
    const payload = payloadFromDraft(form, { includePriority: isEdit.value })
    const saved = isEdit.value ? await store.update(props.rule!.id, payload) : await store.create(payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить правило'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" :aria-label="isEdit ? 'Редактировать правило' : 'Новое правило'">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать правило согласования' : 'Новое правило согласования' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <p v-if="rule?.builtin" class="builtin-note" data-note="builtin">
        Стандартное правило: его можно менять и отключать. «Сбросить» на странице правил вернёт исходный вид.
      </p>

      <div v-if="errorMessage" class="form-error" role="alert">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form @submit.prevent="submit">
        <label class="field">
          <span>Название *</span>
          <input v-model="form.name" type="text" maxlength="200" data-field="name" />
        </label>
        <label class="field">
          <span>Описание</span>
          <textarea v-model="form.description" rows="2" data-field="description"></textarea>
        </label>

        <div class="row">
          <label class="field">
            <span>Действие</span>
            <select v-model="form.action" data-field="action">
              <option v-for="o in ACTION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </label>
          <label class="field checkbox-field">
            <input v-model="form.enabled" type="checkbox" data-field="enabled" />
            <span>Правило включено</span>
          </label>
        </div>
        <p class="hint" data-hint="action">{{ actionHint }}</p>

        <fieldset class="block" data-block="target">
          <legend>Порт, которому применяются изменения</legend>
          <div class="triple">
            <label class="field">
              <span>Роль</span>
              <select v-model="form.target.role" data-field="target-role">
                <option v-for="o in ROLE_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Режим</span>
              <select v-model="form.target.mode" data-field="target-mode">
                <option v-for="o in MODE_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>VLAN</span>
              <select v-model="form.target.vlans" data-field="target-vlans">
                <option v-for="o in VLAN_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset class="block" data-block="source">
          <legend>Соседний порт (откуда берутся значения)</legend>
          <div class="triple">
            <label class="field">
              <span>Роль</span>
              <select v-model="form.source.role" data-field="source-role">
                <option v-for="o in ROLE_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Режим</span>
              <select v-model="form.source.mode" data-field="source-mode">
                <option v-for="o in MODE_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>VLAN</span>
              <select v-model="form.source.vlans" data-field="source-vlans">
                <option v-for="o in VLAN_CONDITION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset class="block" data-block="relation">
          <legend>Отношение значений двух портов</legend>
          <div class="triple">
            <label class="field">
              <span>Роли</span>
              <select v-model="form.relation.role" data-field="relation-role">
                <option v-for="o in RELATION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Режимы</span>
              <select v-model="form.relation.mode" data-field="relation-mode">
                <option v-for="o in RELATION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Наборы VLAN</span>
              <select v-model="form.relation.vlans" data-field="relation-vlans">
                <option v-for="o in RELATION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset class="block" data-block="apply">
          <legend>Что порт берёт у соседа</legend>
          <div class="apply-row">
            <label class="field checkbox-field">
              <input v-model="form.apply.role" type="checkbox" data-field="apply-role" :disabled="isUnion" />
              <span>Роль</span>
            </label>
            <label class="field checkbox-field">
              <input v-model="form.apply.mode" type="checkbox" data-field="apply-mode" :disabled="isUnion" />
              <span>Режим</span>
            </label>
            <label class="field">
              <span>VLAN</span>
              <select v-model="form.apply.vlans" data-field="apply-vlans">
                <option v-for="o in VLAN_POLICY_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </label>
          </div>
        </fieldset>

        <p v-if="isUnion" class="hint" data-hint="union">
          «Объединить» меняет оба порта сразу: каждый получает объединение наборов VLAN обоих портов, ни один VLAN не снимается, направление выбирать
          не нужно. Роль и режим с этой политикой не сочетаются — их порт берёт у соседа.
        </p>
        <p v-if="isAllVlans" class="hint" data-hint="all">
          «Все VLAN» назначает порту все VLAN его устройства (как галочка «Все VLAN» в форме устройства), а не номера VLAN соседа; уже назначенные
          VLAN не снимаются. Если у устройств разные наборы VLAN, наборы на концах линии могут остаться разными — об этом предупредит план. В режиме
          access «Все VLAN» невозможны.
        </p>
        <p v-if="symmetricHint" class="hint warn" data-hint="symmetric">
          Условия на оба порта одинаковы: правило подходит каждому из них, и автоматически его применить нельзя — направление придётся выбирать вручную.
          Различите условия (например, у одного порта «VLAN не назначены совсем», у другого — «назначены»).
        </p>

        <div class="sentence" data-sentence>
          <span class="sentence-title">Как читается правило</span>
          {{ sentence }}
        </div>

        <div class="modal-foot">
          <button type="button" class="btn btn-secondary" @click="$emit('close')">Отмена</button>
          <button type="submit" class="btn btn-primary" :disabled="saving">{{ isEdit ? 'Сохранить' : 'Создать правило' }}</button>
        </div>
      </form>
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
  max-width: 680px;
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
.builtin-note {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 10px;
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
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
  margin-bottom: 10px;
}
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 14px;
  align-items: end;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12.5px;
}
.hint {
  margin: -4px 0 12px;
  font-size: 12px;
  color: var(--ink-muted);
}
.hint.warn {
  color: var(--ink);
  background: var(--status-warn-soft);
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  padding: 7px 9px;
  margin: 0 0 12px;
}
.block {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 8px 12px 2px;
  margin: 0 0 12px;
}
.block legend {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0 6px;
}
.triple {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.apply-row {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 16px;
  align-items: end;
}
.sentence {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.5;
}
.sentence-title {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 3px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .triple,
  .apply-row,
  .row {
    grid-template-columns: 1fr;
  }
}
</style>
