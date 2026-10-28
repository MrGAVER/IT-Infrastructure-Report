import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Connection } from '../../api/types'
import { useConnectionDraft } from '../useConnectionDraft'
import { useConnectionPortsDialog } from '../useConnectionPortsDialog'
import { connection, device, iface, setupConnectionStores } from './connectionFormTestkit'

const devices = [device('dev-1', 'alpha'), device('dev-2', 'beta')]

function setup(conn: Connection | null = connection()) {
  const stores = setupConnectionStores({ devices, interfaces: [iface('if-a', 'dev-1'), iface('if-b', 'dev-2')] })
  const draft = useConnectionDraft({ connection: () => conn, prefill: () => null })
  const refresh = vi.fn(async () => {})
  const dialog = useConnectionPortsDialog(draft, refresh)
  return { stores, draft, dialog, refresh }
}

beforeEach(() => vi.clearAllMocks())

describe('useConnectionPortsDialog', () => {
  it('по умолчанию окно закрыто', () => {
    const { dialog } = setup()
    expect(dialog.endpoint.value).toBeNull()
    expect(dialog.deviceLabel.value).toBe('')
  })

  it('open(source) открывает окно портов исходного устройства', () => {
    const { dialog } = setup()
    dialog.open('source')
    expect(dialog.endpoint.value).toBe('source')
    expect(dialog.deviceId.value).toBe('dev-1')
    expect(dialog.deviceLabel.value).toBe('alpha')
  })

  it('open(destination) — конечного устройства', () => {
    const { dialog } = setup()
    dialog.open('destination')
    expect(dialog.deviceId.value).toBe('dev-2')
    expect(dialog.deviceLabel.value).toBe('beta')
  })

  it('close закрывает окно', () => {
    const { dialog } = setup()
    dialog.open('source')
    dialog.close()
    expect(dialog.endpoint.value).toBeNull()
  })

  it('onSaved: порт на месте — выбор сохраняется, окно закрывается, сверка перезапрашивается', () => {
    const { dialog, draft, refresh } = setup()
    dialog.open('source')
    dialog.onSaved()
    expect(draft.form.source_interface_id).toBe('if-a')
    expect(dialog.endpoint.value).toBeNull()
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('onSaved: порт исходной стороны удалён в окне — выбор сбрасывается, конечной стороны не затрагивается', () => {
    const { dialog, draft, stores } = setup()
    stores.catalogs.items['interfaces'] = [iface('if-b', 'dev-2')] as never
    dialog.open('source')
    dialog.onSaved()
    expect(draft.form.source_interface_id).toBe('')
    expect(draft.form.destination_interface_id).toBe('if-b')
  })

  it('onSaved: порт конечной стороны удалён — сбрасывается только он', () => {
    const { dialog, draft, stores } = setup()
    stores.catalogs.items['interfaces'] = [iface('if-a', 'dev-1')] as never
    dialog.open('destination')
    dialog.onSaved()
    expect(draft.form.destination_interface_id).toBe('')
    expect(draft.form.source_interface_id).toBe('if-a')
  })

  it('onSaved при закрытом окне ничего не сбрасывает', () => {
    const { dialog, draft, stores } = setup()
    stores.catalogs.items['interfaces'] = [] as never
    dialog.onSaved()
    expect(draft.form.source_interface_id).toBe('if-a')
    expect(draft.form.destination_interface_id).toBe('if-b')
  })
})
