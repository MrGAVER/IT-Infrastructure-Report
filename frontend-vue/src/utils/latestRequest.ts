/** Защита от перекрывающихся запросов: результат разрешено применять только последнему запущенному (B-02 код-ревью main @ b375f58).
 *
 * Без неё два `reload()` подряд (после сохранения формы и по событию обновления) могли закончиться в обратном порядке: ответ на ПЕРВЫЙ
 * запрос приходил позже ответа на второй и затирал свежий список устаревшим, а `loading` сбрасывался по окончании первого, пока второй
 * ещё шёл. Один экземпляр — на один поток загрузки, на уровне модуля стора (как `latestRequest` в auditLog.ts и connectionsDashboard.ts).
 *
 * Пример:
 *   const latest = createLatestRequest()
 *   async reload() {
 *     const isLatest = latest.begin()
 *     this.loading = true
 *     try {
 *       const res = await api.get(...)
 *       if (!isLatest()) return // устаревший ответ отбрасывается; finally ниже его `loading` не трогает
 *       this.all = res.items
 *     } catch (e) {
 *       if (isLatest()) this.error = ...
 *     } finally {
 *       if (isLatest()) this.loading = false
 *     }
 *   }
 */
export function createLatestRequest() {
  let current = 0
  return {
    /** Начинает новый запрос; возвращённая функция отвечает, остаётся ли он последним запущенным. */
    begin(): () => boolean {
      const id = ++current
      return () => id === current
    },
  }
}
