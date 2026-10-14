<script setup lang="ts">
// Окно выбора значения «Все VLAN» / набора VLAN для порта, у которого оно расходится с портом на другом конце
// подключения. Открывается, когда пользователь приводит порты к одному виду («Применить конфигурацию соседа» /
// «Применить текущую конфигурацию») и признак «Все VLAN» у них разный (utils/allVlans.ts).
//
// Два варианта:
//  * «Как у источника» — значение порта, с которого берётся конфигурация: «Все VLAN» либо его набор, перенесённый на VLAN
//    устройства порта по номерам (номера, которых у устройства нет, не назначаются — окно об этом предупреждает);
//  * «Другое значение» — любое значение вручную: окно выбора VLAN с поиском и галочкой «Все VLAN» (PortVlanPickerModal.vue).
//
// Компонент ничего не пишет: «Применить» отдаёт выбранное значение родителю (confirm), «Отмена» — cancel.
//
// @example
// <AllVlansChoiceModal
//   port-label="«Gi0/1» (SW-2)" source-label="текущего порта" description="У соседа стоит «Все VLAN», у этого порта — нет."
//   :source-value="{ allVlans: true, vlanIds: [] }" :missing="[]" :options="vlanOptions"
//   @confirm="(value) => write(value)" @cancel="close()"
// />
import { computed, ref } from 'vue'
import type { VLANDefinition } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { describeVlanValue, pickerSelection, toggleValueAll, toggleValueVlan, type VlanValue } from '../utils/allVlans'
import { formatVlans } from '../utils/portConfig'
import PortVlanPickerModal from './PortVlanPickerModal.vue'

const props = defineProps<{
  /** Порт, которому записывается значение, вместе с устройством: «Gi0/1» (SW-2). */
  portLabel: string
  /** Чьё значение предлагается по умолчанию: «текущего порта», «порта соседа «Gi0/24» (SW-2)». */
  sourceLabel: string
  /** Что именно разошлось — одна фраза над вариантами. */
  description: string
  /** Значение источника, уже перенесённое на VLAN устройства порта (utils/allVlans.ts:valueFromSource). */
  sourceValue: VlanValue
  /** Номера VLAN источника, которых нет у устройства порта: они в значение не вошли. */
  missing: readonly number[]
  /** VLAN, допустимые устройству порта. */
  options: VLANDefinition[]
}>()
const emit = defineEmits<{
  confirm: [value: VlanValue]
  cancel: []
}>()

const choice = ref<'source' | 'other'>('source')
// Исходная точка «другого» значения — значение источника: его проще поправить, чем собирать заново.
const other = ref<VlanValue>({ allVlans: props.sourceValue.allVlans, vlanIds: [...props.sourceValue.vlanIds] })
const pickerOpen = ref(false)

const sourceText = computed(() => describeVlanValue(props.sourceValue, props.options))
const otherText = computed(() => describeVlanValue(other.value, props.options))
const result = computed<VlanValue>(() => (choice.value === 'source' ? props.sourceValue : other.value))

const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('cancel'))
</script>

<template>
  <div class="overlay" data-testid="all-vlans-choice" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="choice-modal card" role="dialog" aria-modal="true" aria-labelledby="all-vlans-choice-title">
      <div class="choice-head">
        <h3 id="all-vlans-choice-title">VLAN порта {{ portLabel }}</h3>
        <button type="button" class="icon-btn" aria-label="Отмена" @click="emit('cancel')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="choice-desc">{{ description }} Какое значение установить порту?</p>

      <label class="choice-option">
        <input v-model="choice" type="radio" value="source" name="all-vlans-choice" data-testid="choice-source" />
        <span>
          <b>Как у {{ sourceLabel }}:</b>
          <span class="choice-value" data-testid="choice-source-text">{{ sourceText }}</span>
        </span>
      </label>
      <small v-if="choice === 'source' && missing.length" class="choice-note" data-testid="choice-missing">
        У устройства порта нет VLAN {{ formatVlans(missing) }} — они не будут назначены.
      </small>

      <label class="choice-option">
        <input v-model="choice" type="radio" value="other" name="all-vlans-choice" data-testid="choice-other" />
        <span><b>Другое значение</b></span>
      </label>
      <div v-if="choice === 'other'" class="choice-other">
        <span class="choice-value" data-testid="choice-other-text">{{ otherText }}</span>
        <button type="button" class="btn btn-secondary" data-testid="choice-pick" @click="pickerOpen = true">Выбрать VLAN…</button>
      </div>

      <div class="choice-foot">
        <button type="button" class="btn btn-secondary" @click="emit('cancel')">Отмена</button>
        <button type="button" class="btn btn-primary" data-testid="choice-apply" @click="emit('confirm', result)">Применить</button>
      </div>
    </div>
  </div>

  <PortVlanPickerModal
    v-if="pickerOpen"
    :title="`VLAN порта ${portLabel}`"
    :options="options"
    :selected-ids="pickerSelection(other, options)"
    :all-vlans="other.allVlans"
    @toggle-vlan="(id, checked) => (other = toggleValueVlan(other, id, checked, options))"
    @toggle-all="(checked) => (other = toggleValueAll(checked))"
    @close="pickerOpen = false"
  />
</template>

<style scoped>
/* Выше диалогов редактора портов (70), из которых окно открывается, и ниже окна выбора VLAN (75). */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 74;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 60px 16px;
  overflow-y: auto;
}
.choice-modal {
  width: 100%;
  max-width: 460px;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.choice-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.choice-head h3 {
  font-family: var(--font-display);
  font-size: 14.5px;
  margin: 0;
}
.choice-desc {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin: 0 0 4px;
}
.choice-option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink);
  cursor: pointer;
}
.choice-option input {
  accent-color: var(--brand);
  margin-top: 2px;
}
.choice-value {
  margin-left: 4px;
  color: var(--ink);
}
.choice-note {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: -2px 0 2px 24px;
}
.choice-other {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 2px 24px;
  font-size: 12.5px;
}
.choice-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
