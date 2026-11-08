import { config, enableAutoUnmount } from '@vue/test-utils'
import { afterEach } from 'vitest'
import type { ComponentPublicInstance } from 'vue'
import { MODAL_TELEPORT_DISABLED } from '../components/baseModalKeys'

// F-03 (код-ревью main): BaseModal выносит каждое окно в <body> через Teleport. Тесты большинства окон ищут их внутри обёртки
// (wrapper.find / findComponent), поэтому по умолчанию Teleport окон отключён: содержимое рисуется на месте, а дерево компонентов
// остаётся настоящим (заглушка Teleport из VTU при перерисовке пересоздаёт вложенные компоненты).
//
// FE-05 (ревью ветки fix/code-review-main-f06-stage2-f05): раньше решение принимал сам BaseModal — по имени компонента-владельца через
// getCurrentInstance(), то есть боевой код знал о тестах. Теперь BaseModal читает обычный булев ключ (baseModalKeys.ts), а решение
// «какому окну нужен настоящий Teleport» принимает только тестовая инфраструктура: ключ задаётся здесь, на уровне приложения (true),
// и переопределяется для окон из списка ниже. Тест, которому нужно окно в <body> для любого компонента, подключает
// `realModalTeleport` (src/__tests__/realModalTeleport.ts) явно: `mount(X, { global: { ...realModalTeleport } })`.
//
// Список — окна, которые телепортировались в <body> ещё до BaseModal: их тесты (и тесты их родителей) ищут содержимое в document.body
// (DOMWrapper(document.body)). Таких спеков не шесть, а двадцать два (родительские формы тоже открывают эти окна и ищут их в <body>),
// поэтому вынести список по спекам оказалось в несколько раз дороже, чем оценивал отчёт ревью. Сам перенос в <body> у любого окна
// проверяет BaseModal.spec.ts.
const TELEPORTED_BEFORE_BASE_MODAL = new Set([
  'CatalogRecordFormModal',
  'DevicePortsModal',
  'PortConfigEditModal',
  'QuickAddModal',
  'StackMemberAddConfirmModal',
  'StackVlanRemoveDialog',
])
config.global.provide = { ...config.global.provide, [MODAL_TELEPORT_DISABLED]: true }
config.global.mixins = [
  ...(config.global.mixins ?? []),
  {
    // Каждый компонент передаёт потомкам значение ключа: окно из списка — «Teleport настоящий» (false), остальные — то, что задано на
    // уровне приложения (по умолчанию true, а `realModalTeleport` в mount() даёт false). BaseModal берёт ближайшее значение, то есть
    // значение компонента-владельца, как и раньше.
    provide(this: ComponentPublicInstance) {
      const type = this.$.type as { __name?: string; name?: string }
      const name = type.__name ?? type.name ?? ''
      const appLevel = this.$.appContext.provides[MODAL_TELEPORT_DISABLED as symbol] ?? true
      return { [MODAL_TELEPORT_DISABLED as symbol]: TELEPORTED_BEFORE_BASE_MODAL.has(name) ? false : appLevel }
    },
  },
]

// Каждый смонтированный в тесте компонент снимается после теста сам, поэтому тест не обязан помнить про wrapper.unmount()
// (рекомендация 5 раздела 8 ревью merge/review-f06-stage2-f05-executors). Без этого незакрытые окна, таймеры и слушатели window
// переживали тест: таймер пересчёта маршрутов диаграммы стрелял после его конца и ронял прогон с кодом 1 (R2-02), а открытые окна
// оставались в общем стеке модуля modalLayer и влияли на следующие тесты файла. Вызывать enableAutoUnmount в самих спеках больше
// не нужно (VTU разрешает один вызов на процесс — второй бросает ошибку); тест, которому нужен unmount посреди теста, по-прежнему
// вызывает wrapper.unmount() сам.
enableAutoUnmount(afterEach)
