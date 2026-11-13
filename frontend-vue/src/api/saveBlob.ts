// ИБ-02 (ревью merge/review-r3-executors): «создать blob-ссылку, кликнуть, убрать» было написано дважды — в api/reports.ts (downloadReport)
// и в stores/diagram.ts (exportAs) — и в обоих местах ссылка освобождалась сразу после click(). Теперь это одно место.

/**
 * Через сколько миллисекунд после клика blob-ссылка освобождается. Не сразу: click() только ставит загрузку в очередь браузера, и в части
 * браузеров немедленный `URL.revokeObjectURL` обрывает её, особенно у крупных файлов (экспорт диаграммы, отчёт на тысячи строк).
 * Утечка за это время невелика: ссылка держит один blob, который к тому же уже лежит в памяти страницы.
 */
export const BLOB_URL_REVOKE_DELAY_MS = 30_000

/**
 * Предлагает браузеру сохранить `blob` в файл с именем `filename` (скрытая ссылка с атрибутом download).
 *
 * @example
 *   const { blob, filename } = await exportDiagram(id, 'svg')
 *   saveBlob(blob, filename)
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  // Освобождение назначается сразу после создания ссылки: даже если click() бросит исключение, ссылка не останется навсегда.
  setTimeout(() => URL.revokeObjectURL(url), BLOB_URL_REVOKE_DELAY_MS)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
  }
}
