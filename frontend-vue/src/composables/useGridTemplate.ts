// Загрузка и сохранение Excel-шаблона конструктора отчётов для grid-редактора: сам шаблон, справочник сущностей для вставки полей,
// название/описание и состояние запросов. Листы (config.sheets) принадлежат редактору сетки (useReportGrid) и передаются сюда ссылкой.
import { onMounted, ref, type Ref } from 'vue'
import { getReportEntities } from '../api/reportEntities'
import { getReportTemplate, saveReportTemplate } from '../api/reportTemplates'
import type { GridConfig, GridSheet, ReportEntityMeta, ReportTemplate } from '../api/types'
import { newSheet } from '../utils/reportGridModel'
import { useToast } from './useToast'

export function useGridTemplate(templateId: string, sheets: Ref<GridSheet[]>) {
  const { notify } = useToast()

  const loading = ref(true)
  const saving = ref(false)
  const errorMessage = ref<string | null>(null)
  const template = ref<ReportTemplate | null>(null)
  const entities = ref<ReportEntityMeta[]>([])

  const name = ref('')
  const description = ref('')

  onMounted(async () => {
    try {
      const [t, e] = await Promise.all([getReportTemplate(templateId), getReportEntities()])
      template.value = t
      entities.value = e
      name.value = t.name
      description.value = t.description ?? ''
      const cfg = t.config as unknown as GridConfig
      sheets.value = cfg.sheets && cfg.sheets.length ? cfg.sheets : [newSheet(1)]
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить шаблон'
    } finally {
      loading.value = false
    }
  })

  async function save() {
    errorMessage.value = null
    if (!name.value.trim()) {
      errorMessage.value = 'Укажите название шаблона.'
      return
    }
    saving.value = true
    try {
      const config: GridConfig = { sheets: sheets.value }
      await saveReportTemplate(templateId, {
        name: name.value.trim(),
        description: description.value.trim() || null,
        format: 'xlsx',
        config: config as unknown as Record<string, unknown>,
      })
      notify('Шаблон сохранён', 'success')
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить шаблон'
    } finally {
      saving.value = false
    }
  }

  return { loading, saving, errorMessage, template, entities, name, description, save }
}
