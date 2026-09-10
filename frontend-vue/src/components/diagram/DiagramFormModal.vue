<script setup lang="ts">
// Форма СОЗДАНИЯ диаграммы — редактирования метаданных существующей диаграммы намеренно нет:
// раздел 7 ТЗ не содержит PUT /diagrams/{id} для scope_filter/group_by/collapse_threshold,
// только create/regenerate/duplicate/delete и отдельные PUT для раскладки/состояния групп.
// Изменить область охвата уже созданной диаграммы можно только создав новую (или продублировав
// и переоткрыв в этой форме заново — сама форма правки не предлагает, ограничение API).
import { computed, onMounted, reactive, ref } from 'vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { createDiagram, GROUP_BY_OPTIONS, type DiagramGroupBy } from '../../api/diagrams'
import { useToast } from '../../composables/useToast'

const emit = defineEmits<{ close: []; created: [id: string] }>()
const { notifyError } = useToast()
const catalogs = useCatalogsStore()
const vlans = useVLANsStore()

const form = reactive({
  name: '',
  group_by: 'structural_unit' as DiagramGroupBy,
  collapse_threshold: 20,
  structural_unit_ids: [] as string[],
  building_ids: [] as string[],
  vlan_ids: [] as string[],
  device_category_ids: [] as string[],
})
const saving = ref(false)

onMounted(async () => {
  await Promise.all([catalogs.ensureLoaded(), vlans.ensureLoaded()])
})

const deviceCategories = computed(() => catalogs.items['device-categories'] ?? [])
const buildings = computed(() => catalogs.items['buildings'] ?? [])
const vlanOptions = computed(() => vlans.allDefinitions)

function selectedValues(event: Event): string[] {
  return Array.from((event.target as HTMLSelectElement).selectedOptions).map((o) => o.value)
}

async function save() {
  if (!form.name.trim()) {
    notifyError(new Error('Укажите название диаграммы'))
    return
  }
  saving.value = true
  try {
    const scope_filter: Record<string, string[]> = {}
    if (form.structural_unit_ids.length) scope_filter.structural_unit_ids = form.structural_unit_ids
    if (form.building_ids.length) scope_filter.building_ids = form.building_ids
    if (form.vlan_ids.length) scope_filter.vlan_ids = form.vlan_ids
    if (form.device_category_ids.length) scope_filter.device_category_ids = form.device_category_ids

    const created = await createDiagram({
      name: form.name.trim(),
      group_by: form.group_by,
      collapse_threshold: form.collapse_threshold,
      scope_filter,
    })
    emit('created', created.id)
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <form class="modal card" @submit.prevent="save">
      <h2>Новая диаграмма</h2>

      <label class="field">
        <span>Название</span>
        <input v-model="form.name" type="text" required autofocus placeholder="Например: Филиал Москва" />
      </label>

      <div class="field-row">
        <label class="field">
          <span>Группировка узлов</span>
          <select v-model="form.group_by">
            <option v-for="opt in GROUP_BY_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </label>
        <label class="field">
          <span>Порог сворачивания в группу</span>
          <input v-model.number="form.collapse_threshold" type="number" min="1" />
        </label>
      </div>

      <fieldset class="scope-fieldset">
        <legend>Область охвата (пусто — вся инфраструктура)</legend>
        <div class="field-row">
          <label class="field">
            <span>Структурные единицы</span>
            <select multiple size="4" :value="form.structural_unit_ids" @change="form.structural_unit_ids = selectedValues($event)">
              <option v-for="u in catalogs.structuralUnits" :key="u.id" :value="u.id">{{ u.name }}</option>
            </select>
          </label>
          <label class="field">
            <span>Здания</span>
            <select multiple size="4" :value="form.building_ids" @change="form.building_ids = selectedValues($event)">
              <option v-for="b in buildings" :key="b.id" :value="b.id">{{ b.name }}</option>
            </select>
          </label>
        </div>
        <div class="field-row">
          <label class="field">
            <span>VLAN</span>
            <select multiple size="4" :value="form.vlan_ids" @change="form.vlan_ids = selectedValues($event)">
              <option v-for="v in vlanOptions" :key="v.id" :value="v.id">{{ v.vlan_id }} — {{ v.name }}</option>
            </select>
          </label>
          <label class="field">
            <span>Категории устройств</span>
            <select multiple size="4" :value="form.device_category_ids" @change="form.device_category_ids = selectedValues($event)">
              <option v-for="c in deviceCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
        </div>
      </fieldset>

      <div class="modal-actions">
        <button type="button" class="btn btn-secondary" @click="emit('close')">Отмена</button>
        <button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? 'Создание…' : 'Создать' }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}
.modal {
  width: 640px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
h2 {
  margin: 0;
  font-size: 15px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
  flex: 1;
}
.field input,
.field select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.field-row {
  display: flex;
  gap: 16px;
}
.scope-fieldset {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.scope-fieldset legend {
  font-size: 11px;
  color: var(--ink-muted);
  padding: 0 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
</style>
