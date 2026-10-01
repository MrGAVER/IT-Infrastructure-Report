<script setup lang="ts">
// Проверка расхождения ролей у пары портов-соседей одного подключения (дашборд «Подключения»).
// Роль порта — управление / передача данных — хранится на самом порту; здесь пользователь видит
// обе стороны рядом и решает: одобрить расхождение как допустимое (например, порт управления
// сервера включён в порт коммутатора, настроенный на передачу данных), либо привести роль одного
// порта к роли другого. Статус после любого действия пересчитывает сервер — клиент только
// подставляет его в список.
import { computed, ref } from 'vue'
import { setPortRole } from '../api/portConfig'
import type { Connection } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useConnectionsDashboardStore } from '../stores/connectionsDashboard'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import { roleLabel } from '../utils/portConfig'

const props = defineProps<{ connection: Connection }>()
const emit = defineEmits<{ close: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const dashboard = useConnectionsDashboardStore()
const { notify } = useToast()

const busy = ref(false)
const errorMessage = ref<string | null>(null)

// Своя копия записи, а не строка из стора: список постраничный и с фильтрами, и после отзыва
// одобрения строка может исчезнуть со страницы (например, при фильтре «Одобренные»), хотя окно
// проверки ещё открыто. Копию обновляем ответом сервера.
const current = ref<Connection>(props.connection)
const isApproved = computed(() => current.value.port_config_status === 'approved')
const isMismatch = computed(() => current.value.port_config_status === 'mismatch')

async function run(action: () => Promise<void>, fallbackError: string) {
  busy.value = true
  errorMessage.value = null
  try {
    await action()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : fallbackError
  } finally {
    busy.value = false
  }
}

function approve() {
  return run(async () => {
    await dashboard.approve([current.value.id])
    notify('Расхождение ролей портов одобрено', 'success')
    emit('close')
  }, 'Не удалось одобрить расхождение')
}

function revoke() {
  return run(async () => {
    current.value = await dashboard.revokeApproval(current.value.id)
    notify('Одобрение отозвано — расхождение снова требует проверки', 'info')
  }, 'Не удалось отозвать одобрение')
}

/** keepSource=true — порт назначения получает роль порта-источника, и наоборот. */
function align(keepSource: boolean) {
  const c = current.value
  const role = keepSource ? c.source_port_role : c.destination_port_role
  const targetInterfaceId = keepSource ? c.destination_interface_id : c.source_interface_id
  if (!role) return Promise.resolve()
  return run(async () => {
    catalogs.replaceInterface(await setPortRole(targetInterfaceId, role))
    await dashboard.refreshAfterChange()
    notify('Роль порта обновлена — роли портов подключения совпадают', 'success')
    emit('close')
  }, 'Не удалось изменить роль порта')
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" aria-label="Конфигурация портов подключения">
      <div class="modal-head">
        <h2>Конфигурация портов подключения</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <div class="pair">
        <div class="side">
          <div class="side-title">Источник</div>
          <div class="devname">{{ current.source_device_name }}</div>
          <div class="portname mono">{{ current.source_interface_name }}</div>
          <div class="role" data-side="source">{{ roleLabel(current.source_port_role) }}</div>
        </div>
        <div class="link-icon"><svg class="icon"><use href="/icons.svg#i-network" /></svg></div>
        <div class="side">
          <div class="side-title">Назначение</div>
          <div class="devname">{{ current.destination_device_name }}</div>
          <div class="portname mono">{{ current.destination_interface_name }}</div>
          <div class="role" data-side="destination">{{ roleLabel(current.destination_port_role) }}</div>
        </div>
      </div>

      <p v-if="isMismatch" class="status warn">⚠ Роли портов различаются, решение не принято.</p>
      <p v-else-if="isApproved" class="status approved">✓ Расхождение одобрено — оно считается допустимым, пока роли портов не изменятся.</p>
      <p v-else class="status">Роли портов совпадают.</p>

      <div class="actions">
        <button v-if="isMismatch" type="button" class="btn btn-primary" data-action="approve" :disabled="busy" @click="approve">
          Одобрить расхождение
        </button>
        <button v-if="isApproved" type="button" class="btn btn-secondary" data-action="revoke" :disabled="busy" @click="revoke">
          Отозвать одобрение
        </button>
        <template v-if="isMismatch || isApproved">
          <button type="button" class="btn btn-secondary" data-action="keep-source" :disabled="busy" @click="align(true)">
            Порту «{{ current.destination_interface_name }}» задать роль как у «{{ current.source_interface_name }}»
          </button>
          <button type="button" class="btn btn-secondary" data-action="keep-destination" :disabled="busy" @click="align(false)">
            Порту «{{ current.source_interface_name }}» задать роль как у «{{ current.destination_interface_name }}»
          </button>
        </template>
      </div>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" @click="$emit('close')">Закрыть</button>
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
  max-width: 620px;
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
.pair {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 10px;
  align-items: stretch;
  margin-bottom: 14px;
}
.side {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.side-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.devname {
  font-weight: 600;
  font-size: 13px;
}
.portname {
  color: var(--ink-muted);
  font-size: 11.5px;
}
.role {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink);
}
.link-icon {
  display: flex;
  align-items: center;
  color: var(--ink-muted);
}
.link-icon .icon {
  width: 18px;
  height: 18px;
}
.status {
  margin: 0 0 14px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.status.warn {
  color: var(--ink);
  background: var(--status-warn-soft);
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  padding: 8px 10px;
}
.status.approved {
  color: var(--status-ok, var(--ink));
}
.actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .pair {
    grid-template-columns: 1fr;
  }
  .link-icon {
    justify-content: center;
    transform: rotate(90deg);
  }
}
</style>
