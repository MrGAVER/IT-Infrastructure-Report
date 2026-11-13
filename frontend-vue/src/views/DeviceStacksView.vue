<script setup lang="ts">
// Пункт 5 правки "создание физического устройства": список стеков — простая карточная лента
// без пагинации/фильтров (по образцу VLANDomainsPanel.vue), а не большая таблица, как у
// DevicesView.vue — стеков в организации ожидаемо на порядки меньше, чем самих устройств.
import { onMounted, ref } from 'vue'
import { useDeviceStacksStore } from '../stores/deviceStacks'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { DeviceStack } from '../api/types'
import DeviceStackFormModal from '../components/DeviceStackFormModal.vue'
import DataLoadNotice from '../components/DataLoadNotice.vue'

const stacks = useDeviceStacksStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

const modalStack = ref<DeviceStack | null>(null)
const modalOpen = ref(false)
const deletingId = ref<string | null>(null)

onMounted(() => stacks.ensureLoaded())

function openCreate() {
  modalStack.value = null
  modalOpen.value = true
}
function openEdit(s: DeviceStack) {
  modalStack.value = s
  modalOpen.value = true
}
function closeModal() {
  modalOpen.value = false
  modalStack.value = null
}
async function onSaved() {
  const wasEdit = modalStack.value !== null
  closeModal()
  await stacks.reload()
  notify(wasEdit ? 'Стек обновлён' : 'Стек добавлен', 'success')
}

async function removeStack(s: DeviceStack) {
  if (!confirm(`Удалить стек «${s.name}»?`)) return
  deletingId.value = s.id
  try {
    await deleteResource('device-stacks', s.id)
    await stacks.reload()
    notify('Стек удалён', 'success')
  } catch (err) {
    // Стек с участниками delete_resource не удалит (REFERENCED_BY_OTHER_RECORDS) — сообщение с
    // бэкенда уже объясняет, что сперва нужно убрать устройства из стека.
    notifyError(err)
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="stacks-view">
    <div class="stacks-head">
      <b>Стеки устройств</b>
      <button v-if="auth.canWrite" type="button" class="btn btn-primary" @click="openCreate">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Стек
      </button>
    </div>

    <div class="card stacks-card">
      <DataLoadNotice v-if="stacks.truncated" kind="incomplete" what="стеков устройств" :loaded="stacks.all.length" :total="stacks.total" />
      <div v-if="stacks.error" class="error-banner">{{ stacks.error }}</div>
      <div v-else-if="stacks.loading && !stacks.loaded" class="empty">Загрузка стеков…</div>
      <div v-else-if="!stacks.all.length" class="empty">Стеки устройств не созданы.</div>

      <div v-for="s in stacks.all" :key="s.id" class="stack-row">
        <div class="stack-main">
          <b>{{ s.name }}</b>
          <span v-if="s.description" class="stack-desc">{{ s.description }}</span>
        </div>
        <div class="stack-actions">
          <button type="button" class="btn btn-secondary" @click="openEdit(s)">Открыть</button>
          <button v-if="auth.canWrite" type="button" class="icon-btn danger" :disabled="deletingId === s.id" aria-label="Удалить стек" @click="removeStack(s)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>
    </div>

    <DeviceStackFormModal v-if="modalOpen" :stack="modalStack" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stacks-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.stacks-head b {
  font-family: var(--font-display);
  font-size: 16px;
}
.stacks-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty {
  font-size: 12.5px;
  color: var(--ink-muted);
  padding: 8px 0;
}
.error-banner {
  color: var(--status-crit);
  font-size: 12.5px;
}
.stack-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.stack-row:last-child {
  border-bottom: none;
}
.stack-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stack-desc {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.stack-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
</style>
