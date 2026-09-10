<script setup lang="ts">
// Список сохранённых диаграмм — раздел 11 ТЗ: "DiagramListView.vue — список диаграмм с
// действиями «Открыть»/«Дублировать»/«Удалить»". Без отдельного Pinia-стора (см. комментарий в
// stores/diagram.ts) — список не имеет состояния сверх самого списка, тот же принцип, что и
// StatCard-подобные простые списковые экраны без сложной клиентской логики.
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteDiagram, duplicateDiagram, listDiagrams, type SavedDiagramSummary } from '../api/diagrams'
import { useToast } from '../composables/useToast'
import DiagramFormModal from '../components/diagram/DiagramFormModal.vue'

const router = useRouter()
const { notify, notifyError } = useToast()

const items = ref<SavedDiagramSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const busyId = ref<string | null>(null)
const createOpen = ref(false)

async function reload() {
  loading.value = true
  error.value = null
  try {
    items.value = await listDiagrams()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить список диаграмм'
  } finally {
    loading.value = false
  }
}

onMounted(reload)

function open(d: SavedDiagramSummary) {
  router.push({ name: 'diagram-detail', params: { id: d.id } })
}

async function duplicate(d: SavedDiagramSummary) {
  busyId.value = d.id
  try {
    await duplicateDiagram(d.id)
    await reload()
    notify('Диаграмма продублирована', 'success')
  } catch (e) {
    notifyError(e)
  } finally {
    busyId.value = null
  }
}

async function remove(d: SavedDiagramSummary) {
  if (!confirm(`Удалить диаграмму «${d.name}»?`)) return
  busyId.value = d.id
  try {
    await deleteDiagram(d.id)
    await reload()
    notify('Диаграмма удалена', 'success')
  } catch (e) {
    notifyError(e)
  } finally {
    busyId.value = null
  }
}

function onCreated(id: string) {
  createOpen.value = false
  router.push({ name: 'diagram-detail', params: { id } })
}
</script>

<template>
  <div class="diagrams-view">
    <div class="filter-bar">
      <h1>Диаграммы топологии сети</h1>
      <div class="spacer"></div>
      <button class="btn btn-secondary" :disabled="loading" @click="reload">
        <svg class="icon"><use href="/icons.svg#i-refresh" /></svg>
        Обновить
      </button>
      <button class="btn btn-primary" @click="createOpen = true">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Новая диаграмма
      </button>
    </div>

    <div v-if="error" class="error-banner card">
      <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
      {{ error }}
    </div>
    <div v-else-if="loading && !items.length" class="loading-banner">Загрузка…</div>
    <div v-else-if="!items.length" class="empty-banner card">Диаграмм пока нет — создайте первую.</div>

    <div v-else class="list">
      <div v-for="d in items" :key="d.id" class="row card">
        <div class="row-main" @click="open(d)">
          <span class="name">{{ d.name }}</span>
          <span class="meta">{{ d.group_by }} · порог сворачивания {{ d.collapse_threshold }}</span>
        </div>
        <div class="row-actions">
          <button class="btn btn-secondary" type="button" @click="open(d)">Открыть</button>
          <button class="btn btn-secondary" type="button" :disabled="busyId === d.id" @click="duplicate(d)">Дублировать</button>
          <button class="icon-btn" type="button" aria-label="Удалить" :disabled="busyId === d.id" @click="remove(d)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>
    </div>

    <DiagramFormModal v-if="createOpen" @close="createOpen = false" @created="onCreated" />
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
h1 {
  font-size: 16px;
  margin: 0;
}
.spacer {
  flex: 1;
}
.error-banner,
.empty-banner,
.loading-banner {
  padding: 20px;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.error-banner {
  color: var(--status-crit);
  display: flex;
  align-items: center;
  gap: 8px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  gap: 12px;
}
.row-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
  flex: 1;
  min-width: 0;
}
.name {
  font-weight: 600;
  font-size: 13px;
}
.meta {
  font-size: 11px;
  color: var(--ink-muted);
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
</style>
