// Состояние ТЕКУЩЕЙ открытой диаграммы (DiagramView.vue) — список сохранённых диаграмм
// (DiagramListView.vue) не нуждается в отдельном сторе, т.к. не имеет собственного сложного
// состояния сверх списка (см. views/DiagramListView.vue, работает с api/diagrams.ts напрямую,
// тот же подход, что ReportTemplatesView.vue для шаблонов отчётов).
import { defineStore } from 'pinia'
import {
  createDiagram as apiCreateDiagram,
  deleteDiagram as apiDeleteDiagram,
  duplicateDiagram as apiDuplicateDiagram,
  exportDiagram as apiExportDiagram,
  getDiagram,
  regenerateDiagram as apiRegenerateDiagram,
  renameDiagram as apiRenameDiagram,
  updateDiagramLayout,
  updateGroupState as apiUpdateGroupState,
  type CreateDiagramPayload,
  type DiagramEdge,
  type DiagramExportFormat,
  type DiagramNode,
  type SavedDiagramDetail,
} from '../api/diagrams'
import { saveBlob } from '../api/saveBlob'
import { createLatestRequest } from '../utils/latestRequest'

// Раздел 12 ТЗ: "дебounced-сохранение раскладки" — не на каждый пиксель drag, а после паузы;
// 600мс — тот же порядок величины, что и debounce поиска в других списковых экранах проекта.
// Таймер — переменная модуля, а не поле state: это не данные, а исключительно тайминг побочного
// эффекта, ему незачем быть реактивным (и не нужно захламлять state приложения).
const LAYOUT_SAVE_DEBOUNCE_MS = 600
let layoutSaveTimer: ReturnType<typeof setTimeout> | null = null
// id диаграммы, ради которой запланировано сохранение: к моменту срабатывания таймера (или принудительной
// отправки) в сторе уже может лежать другая диаграмма — «чужую» раскладку на её id отправлять нельзя.
let pendingLayoutDiagramId: string | null = null

/** Снимает запланированное сохранение; true — оно было (то есть есть неотправленные перемещения). */
function takePendingLayoutSave(): boolean {
  if (!layoutSaveTimer) return false
  clearTimeout(layoutSaveTimer)
  layoutSaveTimer = null
  return true
}

export type DiagramSelection = { kind: 'node'; node: DiagramNode } | { kind: 'edge'; edge: DiagramEdge } | null

// B-02: ответ на более ранний load(id) не должен затереть более поздний (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useDiagramStore = defineStore('diagram', {
  state: () => ({
    diagram: null as SavedDiagramDetail | null,
    loading: false,
    error: null as string | null,
    selection: null as DiagramSelection,
    savingLayout: false,
    exporting: null as DiagramExportFormat | null,
  }),
  getters: {
    nodes: (state): DiagramNode[] => state.diagram?.nodes ?? [],
    edges: (state): DiagramEdge[] => state.diagram?.edges ?? [],
  },
  actions: {
    async load(id: string) {
      const isLatest = latest.begin()
      // Перемещения предыдущей диаграммы, ещё не ушедшие на сервер (окно debounce), отправляем ДО замены
      // this.diagram — иначе таймер сработал бы уже по новой диаграмме и последний сдвиг был бы потерян.
      await this.flushLayoutSave()
      // Пока сохранялась раскладка, пользователь мог открыть другую схему: этот запрос уже не нужен, а его loading = true
      // остался бы висеть, если бы более поздняя загрузка успела закончиться раньше.
      if (!isLatest()) return
      this.loading = true
      this.error = null
      this.selection = null
      try {
        const loaded = await getDiagram(id)
        if (!isLatest()) return // быстрое переключение схем: устаревший ответ не показываем; finally ничего не тронет
        this.diagram = loaded
      } catch (e) {
        if (isLatest()) {
          this.error = e instanceof Error ? e.message : 'Не удалось загрузить диаграмму'
          this.diagram = null
        }
      } finally {
        if (isLatest()) this.loading = false
      }
    },

    async create(payload: CreateDiagramPayload): Promise<SavedDiagramDetail> {
      const summary = await apiCreateDiagram(payload)
      await this.load(summary.id)
      return this.diagram!
    },

    /** Пункт 8 правки "диаграмма топологии сети": переименование — раньше диаграмму нельзя было
     * переименовать вообще, только создать заново под другим именем. errors выбрасывается
     * (а не гасится в this.error, как остальные действия этого стора) — DiagramView.vue должен
     * показать ошибку ПРЯМО В поле переименования (напр. "такое имя уже занято") и оставить
     * режим редактирования открытым для повторной попытки, а не молча провалиться и вернуть
     * старое имя без объяснения. */
    async rename(name: string) {
      if (!this.diagram) return
      const updated = await apiRenameDiagram(this.diagram.id, name)
      this.diagram.name = updated.name
    },

    selectNode(node: DiagramNode) {
      this.selection = { kind: 'node', node }
    },
    selectEdge(edge: DiagramEdge) {
      this.selection = { kind: 'edge', edge }
    },
    clearSelection() {
      this.selection = null
    },

    /** Локально обновляет позицию узла (мгновенный отклик на drag) и планирует дебounced-запись
     * всей текущей раскладки на бэкенд — раздел 4.6 ТЗ (PUT /diagrams/{id}/layout). */
    moveNode(nodeId: string, x: number, y: number) {
      const node = this.diagram?.nodes.find((n) => n.id === nodeId)
      if (!node) return
      node.x = x
      node.y = y
      this.scheduleLayoutSave()
    },

    scheduleLayoutSave() {
      takePendingLayoutSave()
      pendingLayoutDiagramId = this.diagram?.id ?? null
      // Стрелочная функция — лексически захватывает `this` вызова scheduleLayoutSave() (Pinia
      // гарантирует корректный `this` для методов-действий), а не только что созданной обёртки:
      // если бы persistLayout вызывался через отдельную именованную функцию, переданную как
      // ссылка (напр. через универсальный debounce()-хелпер utils/debounce.ts), `this` внутри
      // неё оказался бы undefined — эта же ошибка была замечена и исправлена на этапе разработки.
      layoutSaveTimer = setTimeout(() => {
        layoutSaveTimer = null // сработал — отправлять больше нечего (повторный flush не должен слать запрос)
        void this.persistLayout()
      }, LAYOUT_SAVE_DEBOUNCE_MS)
    },

    /** Немедленно отправляет отложенное сохранение раскладки, если оно запланировано. Вызывать перед тем, как
     * диаграмма в сторе будет заменена (load, regenerate) и при уходе с экрана диаграммы. Без запланированного
     * сохранения ничего не делает. */
    async flushLayoutSave() {
      if (!takePendingLayoutSave()) return
      await this.persistLayout()
    },

    async persistLayout() {
      const diagram = this.diagram
      // Диаграмма могла смениться или исчезнуть (remove, ошибка загрузки) с момента планирования.
      if (!diagram || diagram.id !== pendingLayoutDiagramId) return
      const node_positions = Object.fromEntries(diagram.nodes.map((n) => [n.id, { x: n.x, y: n.y }]))
      this.savingLayout = true
      try {
        await updateDiagramLayout(diagram.id, { node_positions })
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось сохранить раскладку'
      } finally {
        this.savingLayout = false
      }
    },

    /** Клик по свёрнутой группе — разворачивает; клик по обычному узлу-группе, которую хочется
     * свернуть обратно, делает то же в обратную сторону. Раздел 12 ТЗ, задача 3 Агента B:
     * "разворачивание/сворачивание группы по клику". Затем regenerate, чтобы граф пересобрался
     * с учётом нового состояния (список узлов меняется — группа заменяется отдельными
     * устройствами или наоборот) — раздел 13 ТЗ фронтенда просит именно "локальное обновление
     * без полной перезагрузки СТРАНИЦЫ", а не без сетевого запроса вообще. */
    async toggleGroup(groupKey: string, collapse: boolean) {
      if (!this.diagram) return
      await apiUpdateGroupState(this.diagram.id, groupKey, { is_collapsed: collapse })
      await this.regenerate()
    },

    async regenerate() {
      if (!this.diagram) return
      // Пересборка заменяет this.diagram данными сервера: несохранённый сдвиг узла иначе затёрся бы.
      await this.flushLayoutSave()
      this.loading = true
      try {
        const refreshed = await apiRegenerateDiagram(this.diagram.id)
        // regenerate() не возвращает viewport (см. backend/app/api/diagrams.py) — сохраняем
        // текущий, чтобы пересборка графа не сбрасывала масштаб/панораму канваса.
        this.diagram = { ...refreshed, viewport: this.diagram.viewport }
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось пересобрать диаграмму'
      } finally {
        this.loading = false
      }
    },

    async duplicate(): Promise<SavedDiagramDetail | null> {
      if (!this.diagram) return null
      const summary = await apiDuplicateDiagram(this.diagram.id)
      return getDiagram(summary.id)
    },

    async remove() {
      if (!this.diagram) return
      // Диаграмма удаляется — сохранять её раскладку незачем (сервер ответил бы 404). Если удалить не удалось,
      // диаграмма остаётся открытой, и сдвиги нужно вернуть в очередь.
      const hadPendingSave = takePendingLayoutSave()
      try {
        await apiDeleteDiagram(this.diagram.id)
      } catch (e) {
        if (hadPendingSave) this.scheduleLayoutSave()
        throw e
      }
      this.diagram = null
    },

    async exportAs(format: DiagramExportFormat) {
      if (!this.diagram) return
      this.exporting = format
      try {
        const { blob, filename } = await apiExportDiagram(this.diagram.id, format)
        saveBlob(blob, filename)
        // Сервер уже сохранил last_export_format (см. backend/app/api/diagrams.py) — отражаем
        // это в локальном состоянии сразу, без перезапроса всей диаграммы, чтобы сплит-кнопка
        // экспорта (DiagramExportPanel.vue) сменила основной формат немедленно.
        this.diagram.last_export_format = format
      } finally {
        this.exporting = null
      }
    },
  },
})
