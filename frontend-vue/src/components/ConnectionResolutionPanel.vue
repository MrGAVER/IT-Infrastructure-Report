<script setup lang="ts">
// Блок «Расхождение конфигурации портов» формы подключения (ConnectionFormModal.vue): показывается вместо кнопок «Отмена/Сохранить»,
// когда у выбранной пары портов различаются роль, режим или VLAN. Сам ничего не меняет — решение отдаёт событием resolve.
//
// Фокус (FE-08, ревью ветки fix/code-review-main-f06-stage2-f05): панель занимает место кнопок «Отмена / Сохранить», и нажатая «Сохранить»
// уходит из DOM — браузер оставляет фокус на <body> (проверено в Chromium), а пользователю клавиатуры и скринридера приходится искать
// новый блок заново. Поэтому при появлении панель берёт фокус на первое доступное действие. Это не alertdialog: панель лежит внутри
// уже открытого окна, где ловушка фокуса есть, а вложенный «диалог» без своей ловушки и возврата фокуса вводил бы в заблуждение, —
// поэтому подписанная группа, а сам вопрос — role="alert". Возврат фокуса на «Сохранить» по «Вернуться к правке» делает форма.
import { computed, onMounted, ref } from 'vue'
import { canAlignMode as canAlignModeOf, sideLabel, viewDiffers, type ConfigView, type MismatchResolution } from '../utils/connectionPortView'
import { facetsLabel, modeLabel } from '../utils/portConfig'

const props = defineProps<{ mismatch: ConfigView }>()
defineEmits<{ resolve: [resolution: MismatchResolution]; back: [] }>()

const root = ref<HTMLElement | null>(null)
// Один раз, при появлении: когда набор расхождений меняется (пользователь сменил порт), фокус из рук пользователя не забираем.
onMounted(() => root.value?.querySelector<HTMLButtonElement>('button')?.focus())

// Пока блок показан, пользователь может сменить порт, и набор расхождений изменится, — поэтому всё считается от props.
const rolesDiffer = computed(() => viewDiffers(props.mismatch, 'role'))
// Режим выравнивается каскадом (режим известен у обоих портов); VLAN правят в окне портов устройства.
const canAlignMode = computed(() => canAlignModeOf(props.mismatch))
const hasVlanDiff = computed(() => viewDiffers(props.mismatch, 'vlans'))
</script>

<template>
  <div ref="root" class="resolution" role="group" aria-label="Расхождение конфигурации портов">
    <p class="warning-text" role="alert">
      ⚠ Конфигурации портов различаются ({{ facetsLabel(mismatch.diff) }}): «{{ mismatch.source.name }}» — {{ sideLabel(mismatch.source) }}, «{{
        mismatch.destination.name
      }}» — {{ sideLabel(mismatch.destination) }}. Что сделать перед сохранением?
    </p>
    <div class="resolution-actions">
      <template v-if="rolesDiffer">
        <button type="button" class="btn btn-secondary" data-resolution="keep-source" @click="$emit('resolve', 'keep-source')">
          Порту «{{ mismatch.destination.name }}» задать роль как у «{{ mismatch.source.name }}»
        </button>
        <button type="button" class="btn btn-secondary" data-resolution="keep-destination" @click="$emit('resolve', 'keep-destination')">
          Порту «{{ mismatch.source.name }}» задать роль как у «{{ mismatch.destination.name }}»
        </button>
      </template>
      <template v-if="canAlignMode">
        <button type="button" class="btn btn-secondary" data-resolution="mode-keep-source" @click="$emit('resolve', 'mode-keep-source')">
          Порту «{{ mismatch.destination.name }}» задать режим как у «{{ mismatch.source.name }}» ({{ modeLabel(mismatch.source.mode) }})
        </button>
        <button type="button" class="btn btn-secondary" data-resolution="mode-keep-destination" @click="$emit('resolve', 'mode-keep-destination')">
          Порту «{{ mismatch.source.name }}» задать режим как у «{{ mismatch.destination.name }}» ({{ modeLabel(mismatch.destination.mode) }})
        </button>
        <p class="resolution-hint" data-hint="mode-cascade">
          Режим порта может задаваться группой и должен совпасть у связанных портов: при необходимости он сменится у всей группы и у связанных с ней портов —
          перед применением покажем список последствий.
        </p>
      </template>
      <p v-if="hasVlanDiff" class="resolution-hint" data-hint="port-setup">
        VLAN меняются в окне портов устройства: вернитесь к правке и нажмите «Управлять портами» рядом с выбором порта.
      </p>
      <button type="button" class="btn btn-primary" data-resolution="approve" @click="$emit('resolve', 'approve')">
        Оставить как есть — одобрить расхождение
      </button>
      <button type="button" class="btn btn-secondary" data-resolution="back" @click="$emit('back')">Вернуться к правке</button>
    </div>
  </div>
</template>

<style scoped>
.resolution {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 18px;
  padding: 12px;
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  background: var(--status-warn-soft);
}
.resolution .warning-text {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink);
  line-height: 1.45;
}
.resolution-hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.resolution-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
</style>
