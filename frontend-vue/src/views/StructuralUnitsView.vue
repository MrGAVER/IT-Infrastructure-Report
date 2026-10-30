<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useCatalogsStore, type StructuralUnitNode } from '../stores/catalogs'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { StructuralUnit } from '../api/types'
import StructuralUnitFormModal from '../components/StructuralUnitFormModal.vue'
import StructuralUnitCrudNode from '../components/StructuralUnitCrudNode.vue'

const catalogs = useCatalogsStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

onMounted(() => catalogs.ensureLoaded())

const modal = ref<{ open: boolean; unit: StructuralUnit | null; defaultParentId: string | null }>({
  open: false,
  unit: null,
  defaultParentId: null,
})

function openCreateRoot() {
  modal.value = { open: true, unit: null, defaultParentId: null }
}
function openAddChild(parentId: string) {
  modal.value = { open: true, unit: null, defaultParentId: parentId }
}
function openEdit(node: StructuralUnitNode) {
  modal.value = { open: true, unit: node, defaultParentId: null }
}
function closeModal() {
  modal.value.open = false
}
async function onSaved() {
  const wasEdit = modal.value.unit !== null
  closeModal()
  await catalogs.reload()
  notify(wasEdit ? 'Структурная единица обновлена' : 'Структурная единица добавлена', 'success')
}

async function removeUnit(node: StructuralUnitNode) {
  if (node.children.length) {
    notifyError(new Error('Нельзя удалить единицу, пока у неё есть дочерние — удалите или перенесите их сначала.'))
    return
  }
  if (!confirm(`Удалить структурную единицу «${node.name}»?`)) return
  try {
    await deleteResource('structural-units', node.id)
    await catalogs.reload()
    notify('Структурная единица удалена', 'success')
  } catch (err) {
    notifyError(err)
  }
}
</script>

<template>
  <div class="units-view">
    <div class="toolbar">
      <p class="hint">Иерархический справочник — используется для фильтрации отчётов и устройств по подразделениям (через привязку к зданиям).</p>
      <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreateRoot">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить корневую единицу
      </button>
    </div>

    <div v-if="catalogs.error" class="error-banner card">{{ catalogs.error }}</div>
    <div v-else-if="catalogs.loading && !catalogs.loaded" class="loading-banner">Загрузка…</div>
    <div v-else-if="!catalogs.structuralUnitTree.length" class="empty-banner card">Структурные единицы ещё не заведены.</div>

    <div v-else class="tree card">
      <StructuralUnitCrudNode
        v-for="node in catalogs.structuralUnitTree"
        :key="node.id"
        :node="node"
        :depth="0"
        @add-child="openAddChild"
        @edit="openEdit"
        @remove="removeUnit"
      />
    </div>

    <StructuralUnitFormModal v-if="modal.open" :unit="modal.unit" :default-parent-id="modal.defaultParentId" @close="closeModal" @saved="onSaved" />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
  max-width: 60ch;
}
.error-banner,
.empty-banner {
  padding: 20px;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.tree {
  padding: 4px 0;
}
</style>
