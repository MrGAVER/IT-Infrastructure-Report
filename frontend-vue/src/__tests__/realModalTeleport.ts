import { MODAL_TELEPORT_DISABLED } from '../components/baseModalKeys'

/**
 * Настоящий Teleport для любого окна BaseModal в тесте: окно оказывается в document.body, и искать его надо там
 * (DOMWrapper(document.body)). По умолчанию (setup.ts) окна рисуются на месте.
 *
 * @example
 * mount(Component, { global: { ...realModalTeleport } })
 */
export const realModalTeleport = { provide: { [MODAL_TELEPORT_DISABLED]: false } }
