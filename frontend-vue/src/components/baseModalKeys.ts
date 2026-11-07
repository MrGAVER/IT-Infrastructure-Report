import type { InjectionKey } from 'vue'

/**
 * true — рисовать окно на месте, а не в <body> (Teleport disabled). Ключ нужен только тестам: большинство ищет окно внутри обёртки
 * (wrapper.find), а заглушка Teleport из @vue/test-utils при перерисовке пересоздаёт вложенные компоненты и теряет их состояние.
 * В приложении ключ не задаётся — окна всегда в <body>. По умолчанию в тестах true (src/__tests__/setup.ts); тест, которому нужно окно
 * в <body> (он ищет содержимое в document.body), подключает `realModalTeleport` (src/__tests__/realModalTeleport.ts) — решение
 * принимает тест, а не боевой компонент (FE-05 ревью ветки fix/code-review-main-f06-stage2-f05).
 */
export const MODAL_TELEPORT_DISABLED: InjectionKey<boolean> = Symbol('modalTeleportDisabled')
