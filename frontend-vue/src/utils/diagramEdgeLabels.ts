// Раскладка подписей рёбер диаграммы (UI-22, ревью 2.158.0): подписи портов («Gi1/0/5», «Gi1/0/13») накладывались на нижнюю строку
// узла и друг на друга при параллельных связях. Причины было три, и каждая закрыта отдельной чистой функцией:
//  1. подпись лежала на фиксированных 14 px от Handle, а повёрнутая вдоль наклонной линии она достаёт дальше — и заходила на узел
//     → portLabelDistance считает отступ по размаху повёрнутой подписи;
//  2. засечки соседних портов стоят на узле в нескольких пикселях друг от друга, а подпись шире → computeEdgeLabelLayout разводит
//     соседние концы по «слотам» — разным расстояниям вдоль ребра;
//  3. параллельные связи между одной парой устройств рисуют N одинаковых наборов подписей → при N ≥ 3 полный набор у первой связи
//     и «×N» вместо остальных (edgeLabelTexts).
// Плюс на мелком масштабе подписи нечитаемы и только засоряют картину — edgeLabelsVisible.
// Всё это геометрия и текст без DOM, поэтому проверяется юнит-тестами; компонент ребра только раскладывает результат по разметке.
import { Position } from '@vue-flow/core'
import type { InjectionKey, Ref } from 'vue'
import type { DiagramEdge } from '../api/diagrams'
import { edgeMidLabel, edgeSourcePortLabel, edgeTargetPortLabel, PORT_LABEL_OFFSET } from './diagramFlow'

/** Ниже этого масштаба подписи рёбер скрыты: при 9–10 px шрифта и масштабе 0,6 они меньше 6 px и читаются как грязь на линиях. */
export const EDGE_LABEL_MIN_ZOOM = 0.6
/** Сколько разных расстояний вдоль ребра используется, чтобы развести подписи соседних портов. */
export const PORT_LABEL_SLOTS = 3
/** Шаг между слотами, px канваса. */
export const PORT_LABEL_SLOT_STEP = 16
/** С какого числа параллельных связей между одной парой устройств подписи сворачиваются в «×N». */
export const PARALLEL_GROUP_MIN = 3

// Размеры подписи порта по стилям DiagramConnectionEdge.vue: шрифт 9 px (≈ 5,4 px на символ), padding 1/5 px и рамка 1 px.
const LABEL_CHAR_WIDTH = 5.4
const LABEL_CHROME_WIDTH = 12
const LABEL_HEIGHT = 16
/** Зазор между узлом и ближайшим краем повёрнутой подписи. */
const LABEL_GAP = 4

export function edgeLabelsVisible(zoom: number): boolean {
  return zoom >= EDGE_LABEL_MIN_ZOOM
}

export interface EdgeLabelLayout {
  /** Слот подписи порта у начала ребра: 0…PORT_LABEL_SLOTS − 1. */
  sourceSlot: number
  /** Слот подписи порта у конца ребра. */
  targetSlot: number
  /** Сколько связей соединяют ту же пару устройств (включая эту). */
  parallelCount: number
  /** Номер этой связи среди параллельных: 0 — первая. */
  parallelIndex: number
}

export type EdgeLabelLayoutMap = ReadonlyMap<string, EdgeLabelLayout>

/** Раскладка передаётся компонентам рёбер через provide/inject, а не в edge.data: данные ребра остаются ровно контрактом API. */
export const EDGE_LABEL_LAYOUT_KEY: InjectionKey<Ref<EdgeLabelLayoutMap>> = Symbol('diagram-edge-label-layout')

interface EdgeEnd {
  edgeId: string
  role: 'source' | 'target'
  /** Порядковая позиция засечки на узле; у концов без засечки (свёрнутая группа, custom-значок) все хэндлы в одной точке. */
  portIndex: number
}

function pairKey(edge: DiagramEdge): string {
  return edge.source_node_id < edge.target_node_id ? `${edge.source_node_id}|${edge.target_node_id}` : `${edge.target_node_id}|${edge.source_node_id}`
}

/**
 * Слоты подписей портов и группы параллельных связей для всех рёбер диаграммы.
 *
 * Слот — это номер конца среди всех концов рёбер ЭТОГО узла, упорядоченных по положению засечки, по модулю PORT_LABEL_SLOTS:
 * засечки идут вдоль узла равномерно, поэтому соседние по порядку концы — соседи и в пространстве, и им достаются разные слоты.
 * Результат не зависит от порядка рёбер на входе (сортировка по id), иначе подписи прыгали бы при каждой перезагрузке.
 */
export function computeEdgeLabelLayout(edges: readonly DiagramEdge[]): EdgeLabelLayoutMap {
  const endsByNode = new Map<string, EdgeEnd[]>()
  const addEnd = (nodeId: string, end: EdgeEnd) => {
    const list = endsByNode.get(nodeId)
    if (list) list.push(end)
    else endsByNode.set(nodeId, [end])
  }
  const groups = new Map<string, DiagramEdge[]>()

  for (const edge of edges) {
    addEnd(edge.source_node_id, { edgeId: edge.id, role: 'source', portIndex: edge.source_interface?.port_index ?? Number.MAX_SAFE_INTEGER })
    addEnd(edge.target_node_id, { edgeId: edge.id, role: 'target', portIndex: edge.target_interface?.port_index ?? Number.MAX_SAFE_INTEGER })
    const key = pairKey(edge)
    const group = groups.get(key)
    if (group) group.push(edge)
    else groups.set(key, [edge])
  }

  const slots = new Map<string, { source: number; target: number }>()
  for (const ends of endsByNode.values()) {
    ends.sort((a, b) => a.portIndex - b.portIndex || a.edgeId.localeCompare(b.edgeId) || a.role.localeCompare(b.role))
    ends.forEach((end, rank) => {
      const entry = slots.get(end.edgeId) ?? { source: 0, target: 0 }
      entry[end.role] = rank % PORT_LABEL_SLOTS
      slots.set(end.edgeId, entry)
    })
  }

  const layout = new Map<string, EdgeLabelLayout>()
  for (const group of groups.values()) {
    const ordered = [...group].sort((a, b) => a.id.localeCompare(b.id))
    ordered.forEach((edge, index) => {
      const slot = slots.get(edge.id) ?? { source: 0, target: 0 }
      layout.set(edge.id, { sourceSlot: slot.source, targetSlot: slot.target, parallelCount: ordered.length, parallelIndex: index })
    })
  }
  return layout
}

export interface EdgeLabelTexts {
  mid?: string
  source?: string
  target?: string
}

/**
 * Что подписано у ребра. Связь, не входящая в группу из PARALLEL_GROUP_MIN и больше параллельных, подписана как раньше. В группе
 * первая связь несёт полный набор подписей и «×N» в середине, остальные подписей не рисуют: их имена портов остаются в панели
 * сведений по клику на ребро, а на диаграмме не громоздятся N одинаковых наборов поверх друг друга.
 */
export function edgeLabelTexts(edge: DiagramEdge, layout?: EdgeLabelLayout): EdgeLabelTexts {
  const grouped = layout !== undefined && layout.parallelCount >= PARALLEL_GROUP_MIN
  if (grouped && layout.parallelIndex > 0) return {}
  const mid = [edgeMidLabel(edge), grouped ? `×${layout.parallelCount}` : undefined].filter(Boolean).join(' · ') || undefined
  return { mid, source: edgeSourcePortLabel(edge), target: edgeTargetPortLabel(edge) }
}

/**
 * Расстояние от Handle до центра подписи порта вдоль направления «наружу» из узла.
 *
 * Подпись повёрнута на угол линии, поэтому её размах в сторону узла — не половина высоты, а половина проекции повёрнутого
 * прямоугольника на эту ось: у вертикальной линии 55-пиксельная «Gi1/0/13» стоит столбиком и достаёт на ~28 px, а не на 8. Отступ не
 * меньше прежнего PORT_LABEL_OFFSET, чтобы горизонтальные подписи остались там же. К нему прибавляется шаг слота.
 */
export function portLabelDistance(text: string, angleDeg: number, position: Position, slot: number): number {
  const width = text.length * LABEL_CHAR_WIDTH + LABEL_CHROME_WIDTH
  const rad = (angleDeg * Math.PI) / 180
  const sin = Math.abs(Math.sin(rad))
  const cos = Math.abs(Math.cos(rad))
  const towardNodeAxisIsVertical = position === Position.Top || position === Position.Bottom
  const halfExtent = towardNodeAxisIsVertical ? (width / 2) * sin + (LABEL_HEIGHT / 2) * cos : (width / 2) * cos + (LABEL_HEIGHT / 2) * sin
  return Math.max(PORT_LABEL_OFFSET, halfExtent + LABEL_GAP) + slot * PORT_LABEL_SLOT_STEP
}
