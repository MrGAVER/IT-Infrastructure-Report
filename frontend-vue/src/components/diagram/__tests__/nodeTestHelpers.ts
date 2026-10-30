import type { NodeProps } from '@vue-flow/core'

/** Аудит слияния (feature/network-topology-diagram + fix/usability-batch4, находка №7):
 * DiagramGroupNode.spec.ts монтировал `<DiagramGroupNode>` только с `{ id, data, selected }`,
 * приведёнными через `as never` — это глушит проверку типов, а не удовлетворяет её: остальные
 * обязательные поля `NodeProps` (`type`, `connectable`, `position`, `dimensions`, `dragging`,
 * `resizing`, `zIndex`, `events`) физически не передавались. Тест не падал только потому, что Vue
 * логирует предупреждение о недостающем required-пропе, а не бросает исключение, — то есть
 * контракт пропсов компонента не проверялся тестом в полном объёме, несмотря на зелёный прогон.
 *
 * makeNodeProps() собирает ПОЛНЫЙ, корректно типизированный набор пропсов с разумными дефолтами
 * для тех полей, что тестам самих узлов обычно не важны (geometry/drag-state/события) — `data` и
 * `selected` передаются явно на каждый вызов, остальное можно переопределить через overrides.
 *
 * @example
 * const props = makeNodeProps({ id: 'group:1', type: 'group', label: 'X (5)', device_count: 5, x: 0, y: 0 })
 * mount(DiagramGroupNode, { props, global: { stubs: { Handle: true } } })
 */
export function makeNodeProps<Data extends { id: string; type: string }>(data: Data, overrides: Partial<NodeProps<Data>> = {}): NodeProps<Data> {
  return {
    id: data.id,
    type: data.type,
    selected: false,
    connectable: true,
    position: { x: 0, y: 0 },
    dimensions: { width: 0, height: 0 },
    dragging: false,
    resizing: false,
    zIndex: 0,
    data,
    events: {},
    ...overrides,
  } as NodeProps<Data>
}
