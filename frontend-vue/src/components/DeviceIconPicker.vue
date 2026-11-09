<script setup lang="ts">
// Раздел 11 ТЗ: "Компонент выбора иконки устройства (в карточке узла и в форме
// PhysicalDevice/DeviceModel): предпросмотр сгенерированной иконки по умолчанию, либо загрузка
// своего SVG в каталог DiagramIcon и его выбор."
//
// Точный предпросмотр АВТОгенерируемой иконки (подъём по иерархии DeviceCategory — см.
// backend/app/services/diagram_icons.py:resolve_category_style) сознательно НЕ дублируется
// здесь: источник истины один, на бэкенде (build_graph при открытии диаграммы). Дублирование
// этой логики в JS рисковало бы разойтись с бэкендом при будущих правках одной из двух копий —
// вместо этого пункт "Автоматически" в списке просто нейтрально это называет, без попытки
// предсказать итоговые форму/цвет прямо в форме устройства/модели.
import { computed, ref, useId } from 'vue'
import { useCatalogsStore } from '../stores/catalogs'
import { createResource } from '../api/client'
import { useToast } from '../composables/useToast'
import { namespaceSvgIds, sanitizeSvg } from '../utils/sanitizeSvg'
import type { CatalogItem } from '../api/types'

const props = defineProps<{ modelValue: string | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

const catalogs = useCatalogsStore()
const { notifyError } = useToast()

const showUpload = ref(false)
const uploadName = ref('')
const uploadSvg = ref('')
const uploading = ref(false)

const icons = computed(() => catalogs.items['diagram-icons'] ?? [])
const selectedIcon = computed(() => icons.value.find((i) => i.id === props.modelValue))
// Код-ревью п.3.1: предпросмотр — тот же пользовательский svg_markup, что и на канвасе
// диаграммы (см. DiagramDeviceNode.vue), санитизация нужна здесь по той же причине.
// R2-03: предпросмотр может оказаться на одной странице с диаграммой или другим предпросмотром — id внутри иконки получают свой префикс.
const previewUid = useId()
const sanitizedSelectedIconSvg = computed(() =>
  namespaceSvgIds(sanitizeSvg((selectedIcon.value as (CatalogItem & { svg_markup: string }) | undefined)?.svg_markup), `ic${previewUid}`),
)

function onSelect(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', value || null)
}

async function uploadCustomIcon() {
  if (!uploadName.value.trim() || !uploadSvg.value.trim()) {
    notifyError(new Error('Укажите название и SVG-разметку иконки'))
    return
  }
  uploading.value = true
  try {
    const created = await createResource<CatalogItem>('diagram-icons', {
      name: uploadName.value.trim(),
      svg_markup: uploadSvg.value.trim(),
    })
    catalogs.addDiagramIcon(created)
    emit('update:modelValue', created.id)
    showUpload.value = false
    uploadName.value = ''
    uploadSvg.value = ''
  } catch (e) {
    notifyError(e)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="icon-picker">
    <label class="field">
      <span>Иконка на диаграмме топологии сети</span>
      <select class="icon-select" :value="modelValue ?? ''" @change="onSelect">
        <option value="">Автоматически — по категории устройства</option>
        <option v-for="icon in icons" :key="icon.id" :value="icon.id">{{ icon.name }}</option>
      </select>
    </label>

    <!-- eslint-disable-next-line vue/no-v-html -- sanitizedSelectedIconSvg проходит через sanitizeSvg() (utils/sanitizeSvg.ts) -->
    <div v-if="selectedIcon" class="preview" v-html="sanitizedSelectedIconSvg"></div>

    <button type="button" class="btn btn-secondary btn-sm" @click="showUpload = !showUpload">
      {{ showUpload ? 'Отмена' : '+ Загрузить свою иконку' }}
    </button>

    <div v-if="showUpload" class="upload-box">
      <input v-model="uploadName" type="text" placeholder="Название иконки" />
      <textarea v-model="uploadSvg" rows="3" placeholder="<svg>...</svg>"></textarea>
      <button type="button" class="btn btn-primary btn-sm" :disabled="uploading" @click="uploadCustomIcon">
        {{ uploading ? 'Загрузка…' : 'Сохранить иконку' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.icon-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.icon-select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
}
.preview {
  width: 48px;
  height: 48px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--surface-2);
}
.preview :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}
.upload-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px dashed var(--border);
  border-radius: var(--r-s);
}
.upload-box input,
.upload-box textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
.upload-box textarea {
  font-family: var(--font-mono, monospace);
  resize: vertical;
}
.btn-sm {
  align-self: flex-start;
  padding: 4px 10px;
  font-size: 11.5px;
}
</style>
