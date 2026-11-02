<script setup lang="ts">
// Подтверждение снятия общей настройки VLAN со стека. По умолчанию значения на устройствах остаются (поля у них снова
// редактируются); отдельная галочка убирает VLAN и у всех устройств стека — действие необратимое, поэтому оно явно
// описано и не включено по умолчанию.
import { ref, useId } from 'vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

defineProps<{ vlanLabel: string; stackName: string; memberCount: number; busy: boolean; error: string | null }>()
const emit = defineEmits<{ confirm: [removeFromDevices: boolean]; cancel: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('cancel'))
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()
const removeFromDevices = ref(false)
</script>

<template>
  <Teleport to="body">
    <div class="overlay" data-testid="stack-vlan-remove-dialog" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
      <div class="dialog card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
        <h3 :id="titleId">Снять общую настройку VLAN {{ vlanLabel }}?</h3>
        <p class="lead">Стек «{{ stackName }}»: после снятия IP-адрес, префикс и «Управление» этого VLAN снова можно менять на каждом устройстве отдельно.</p>
        <label class="option">
          <input v-model="removeFromDevices" type="checkbox" data-testid="stack-vlan-remove-from-devices" />
          <span>
            Также убрать VLAN у всех устройств стека ({{ memberCount }})
            <small>Значения на устройствах будут потеряны. Не выполнится, если VLAN используется на портах, в группах портов или подинтерфейсах.</small>
          </span>
        </label>
        <p v-if="!removeFromDevices" class="note" data-testid="stack-vlan-remove-keep-note">VLAN и его значения на устройствах останутся.</p>
        <p v-else class="note warn" data-testid="stack-vlan-remove-warn-note">VLAN будет удалён из «VLAN устройства» у всех участников стека.</p>
        <div v-if="error" class="form-error" role="alert" data-testid="stack-vlan-remove-error">{{ error }}</div>
        <div class="foot">
          <button type="button" class="btn btn-secondary" :disabled="busy" data-testid="stack-vlan-remove-cancel" @click="emit('cancel')">Отмена</button>
          <button type="button" class="btn btn-primary" :disabled="busy" data-testid="stack-vlan-remove-confirm" @click="emit('confirm', removeFromDevices)">
            {{ busy ? 'Выполняется…' : removeFromDevices ? 'Снять и убрать у устройств' : 'Снять настройку' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.dialog {
  width: 100%;
  max-width: 460px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h3 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.lead,
.note {
  font-size: 12.5px;
  margin: 0;
}
.note {
  color: var(--ink-muted);
}
.note.warn {
  color: var(--status-warn);
}
.option {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 12.5px;
}
.option small {
  display: block;
  color: var(--ink-muted);
  font-size: 11px;
  margin-top: 2px;
}
.form-error {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--crit-ink);
  border-radius: var(--r-m);
  padding: 8px 10px;
  font-size: 12px;
}
.foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
