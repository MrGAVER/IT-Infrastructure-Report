// Предпросмотр grid-шаблона: отправляет текущие листы на сервер и держит состояние окна предпросмотра (открыто / загрузка / ошибка / результат).
import { ref, type Ref } from 'vue'
import { previewGridConfig } from '../api/reportPreview'
import type { GridPreviewResponse, GridSheet } from '../api/types'

export function useGridPreview(sheets: Ref<GridSheet[]>) {
  const previewOpen = ref(false)
  const previewLoading = ref(false)
  const previewError = ref<string | null>(null)
  const previewResult = ref<GridPreviewResponse | null>(null)

  async function runPreview() {
    previewOpen.value = true
    previewError.value = null
    previewLoading.value = true
    try {
      previewResult.value = await previewGridConfig({ sheets: sheets.value } as unknown as Record<string, unknown>)
    } catch (err) {
      previewError.value = err instanceof Error ? err.message : 'Не удалось построить предпросмотр'
    } finally {
      previewLoading.value = false
    }
  }
  function closePreview() {
    previewOpen.value = false
  }

  return { previewOpen, previewLoading, previewError, previewResult, runPreview, closePreview }
}
