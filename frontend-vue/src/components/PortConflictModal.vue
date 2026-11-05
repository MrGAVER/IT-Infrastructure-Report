<script setup lang="ts">
import { useId } from 'vue'
// Окно решения расхождения порта с соседним портом (значок-предупреждение в строке порта): показывает конфигурацию текущего
// порта и соседнего рядом и даёт применить любую из двух. Само применение — useNeighborSync (applyNeighborConfig /
// applyCurrentConfigToNeighbor); окно только показывает данные и сообщает о выборе.
import BaseModal from './BaseModal.vue'
import type { InterfaceDraftRow, PortConflictInfo } from '../api/types'
import { carriesAllVlans } from '../utils/allVlans'
import { conflictTitle, type ConflictKind } from '../utils/interfaceRowView'

defineProps<{
  /** Порт, у которого разошлись настройки. */
  row: InterfaceDraftRow
  /** Расхождение с соседним портом (из conflicts родителя). */
  conflict: PortConflictInfo | undefined
  kind: ConflictKind
  /** Идёт применение — кнопки недоступны. */
  applying: boolean
}>()
const emit = defineEmits<{
  close: []
  'apply-neighbor': []
  'apply-current': []
}>()

// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()
</script>

<template>
  <BaseModal :offset="60" @close="emit('close')">
    <div class="conflict-modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="conflict-modal-head">
        <h3 :id="titleId">{{ conflictTitle(kind) }}</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="conflict-modal-desc">
        Порт «{{ row.name }}» соединён с портом «{{ conflict?.otherInterfaceName }}» устройства «{{ conflict?.otherDeviceName }}», но их настройки разошлись.
      </p>
      <table class="conflict-compare">
        <thead>
          <tr>
            <th></th>
            <th>Этот порт</th>
            <th>Соседний порт</th>
          </tr>
        </thead>
        <tbody v-if="kind === 'flags'">
          <tr>
            <td>Управление</td>
            <td>{{ row.is_management ? 'Да' : 'Нет' }}</td>
            <td>{{ conflict?.other.is_management ? 'Да' : 'Нет' }}</td>
          </tr>
          <tr>
            <td>Передача данных</td>
            <td>{{ row.is_data_transfer ? 'Да' : 'Нет' }}</td>
            <td>{{ conflict?.other.is_data_transfer ? 'Да' : 'Нет' }}</td>
          </tr>
        </tbody>
        <tbody v-else-if="kind === 'all_vlans'">
          <tr>
            <td>Все VLAN</td>
            <td>{{ carriesAllVlans(row) ? 'Да' : 'Нет' }}</td>
            <td>{{ conflict?.other.all_vlans ? 'Да' : 'Нет' }}</td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr>
            <td>Режим порта</td>
            <td>{{ row.vlan_mode === 'access' ? 'Access' : 'Trunk' }}</td>
            <td>{{ conflict?.other.vlan_mode === 'access' ? 'Access' : 'Trunk' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="conflict-modal-actions">
        <button type="button" class="btn btn-secondary" :disabled="applying" @click="emit('apply-neighbor')">Применить конфигурацию соседа</button>
        <button type="button" class="btn btn-primary" :disabled="applying" @click="emit('apply-current')">Применить текущую конфигурацию</button>
      </div>
      <p v-if="kind === 'vlan_mode'" class="conflict-modal-hint">
        Если порт (свой или соседа) входит в группу или связан с другими портами, режим сменится у всей группы и у связанных портов, чтобы расхождения не
        появились в другом месте. Перед применением будет показан список всех последствий. Если после смены режима у портов разойдётся «Все VLAN», предложим
        выбрать значение.
      </p>
      <p v-if="kind === 'all_vlans'" class="conflict-modal-hint">
        «Все VLAN» у устройств — разные наборы номеров, поэтому значение для порта выбираете вы: как у порта-источника или другое.
      </p>
    </div>
  </BaseModal>
</template>

<style scoped src="../styles/interfaceModal.css"></style>
<style scoped>
.conflict-compare {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.conflict-compare th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}
.conflict-compare td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.conflict-compare tr:last-child td {
  border-bottom: none;
}
.conflict-modal-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 10px 0 0;
}
</style>
