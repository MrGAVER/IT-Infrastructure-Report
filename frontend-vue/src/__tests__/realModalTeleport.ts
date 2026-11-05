import { MODAL_TELEPORT_DISABLED } from '../components/baseModalKeys'

/**
 * Настоящий Teleport для любого окна BaseModal в тесте: окно оказывается в document.body, и искать его надо там
 * (DOMWrapper(document.body)).
 *
 * @example
 * mount(Component, { global: { ...realModalTeleport } })
 */
export const realModalTeleport = { provide: { [MODAL_TELEPORT_DISABLED]: () => false } }
