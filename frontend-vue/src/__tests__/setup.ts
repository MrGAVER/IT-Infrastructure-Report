import { config } from '@vue/test-utils'
import { MODAL_TELEPORT_DISABLED } from '../components/baseModalKeys'

// F-03 (код-ревью main): BaseModal выносит каждое окно в <body> через Teleport. Тесты большинства окон ищут их внутри обёртки
// (wrapper.find / findComponent), поэтому по умолчанию Teleport окон отключён: содержимое рисуется на месте, а дерево компонентов
// остаётся настоящим (заглушка Teleport из VTU при перерисовке пересоздаёт вложенные компоненты).
//
// Исключение — окна, которые телепортировались в <body> ещё до BaseModal: их тесты ищут содержимое в document.body
// (DOMWrapper(document.body)), и для них Teleport остаётся настоящим. Сам перенос в <body> у любого окна проверяет BaseModal.spec.ts.
const TELEPORTED_BEFORE_BASE_MODAL = new Set([
  'CatalogRecordFormModal',
  'DevicePortsModal',
  'PortConfigEditModal',
  'QuickAddModal',
  'StackMemberAddConfirmModal',
  'StackVlanRemoveDialog',
])
config.global.provide = {
  ...config.global.provide,
  [MODAL_TELEPORT_DISABLED]: (modalName: string) => !TELEPORTED_BEFORE_BASE_MODAL.has(modalName),
}
