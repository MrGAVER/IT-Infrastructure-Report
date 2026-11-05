import type { InjectionKey } from 'vue'

/**
 * Решает, рисовать ли окно на месте, а не в <body> (Teleport disabled): получает имя компонента-окна (CatalogRecordFormModal и т. п.),
 * true — на месте. Ключ нужен только тестам: большинство ищет окно внутри обёртки (wrapper.find), а заглушка Teleport из
 * @vue/test-utils при перерисовке пересоздаёт вложенные компоненты и теряет их состояние. В приложении ключ не задаётся —
 * окна всегда в <body>. Настройка тестов — src/__tests__/setup.ts.
 */
export const MODAL_TELEPORT_DISABLED: InjectionKey<(modalName: string) => boolean> = Symbol('modalTeleportDisabled')
