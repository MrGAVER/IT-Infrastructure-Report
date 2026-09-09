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
  updateDiagramLayout,
  updateGroupState as apiUpdateGroupState,
  type CreateDiagramPayload,
  type DiagramEdge,
  type DiagramExportFormat,
  type DiagramNode,
  type SavedDiagramDetail,
} from '../api/diagrams'

// Раздел 12 ТЗ: "дебounced-сохранение раскладки" — не на каждый пиксель drag, а после паузы;
// 600мс — тот же порядок величины, что и debounce поиска в других списковых экранах проекта.
// Таймер — переменная модуля, а не поле state: это не данные, а исключительно тайминг побочного
// эффекта, ему незачем быть реактивным (и не нужно захламлять state приложения).
const LAYOUT_SAVE_DEBOUNCE_MS = 600
let layoutSaveTimer: ReturnType<typeof setTimeout> | null = null

export type DiagramSelection = { kind: 'node'; node: DiagramNode } | { kind: 'edge'; edge: DiagramEdge } | null

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
      this.loading = true
      this.error = null
      this.selection = null
      try {
        this.diagram = await getDiagram(id)
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить диаграмму'
        this.diagram = null
      } finally {
        this.loading = false
      }
    },

    async create(payload: CreateDiagramPayload): Promise<SavedDiagramDetail> {
      const summary = await apiCreateDiagram(payload)
      await this.load(summary.id)
      return this.diagram!
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
      if (layoutSaveTimer) clearTimeout(layoutSaveTimer)
      // Стрелочная функция — лексически захватывает `this` вызова scheduleLayoutSave() (Pinia
      // гарантирует корректный `this` для методов-действий), а не только что созданной обёртки:
      // если бы persistLayout вызывался через отдельную именованную функцию, переданную как
      // ссылка (напр. через универсальный debounce()-хелпер utils/debounce.ts), `this` внутри
      // неё оказался бы undefined — эта же ошибка была замечена и исправлена на этапе разработки.
      layoutSaveTimer = setTimeout(() => {
        void this.persistLayout()
      }, LAYOUT_SAVE_DEBOUNCE_MS)
    },

    async persistLayout() {
      if (!this.diagram) return
      const node_positions = Object.fromEntries(this.diagram.nodes.map((n) => [n.id, { x: n.x, y: n.y }]))
      this.savingLayout = true
      try {
        await updateDiagramLayout(this.diagram.id, { node_positions })
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
      await apiDeleteDiagram(this.diagram.id)
      this.diagram = null
    },

    async exportAs(format: DiagramExportFormat) {
      if (!this.diagram) return
      this.exporting = format
      try {
        const { blob, filename } = await apiExportDiagram(this.diagram.id, format)
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
      } finally {
        this.exporting = null
      }
    },
  },
})
