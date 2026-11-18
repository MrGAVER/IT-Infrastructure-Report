import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDeviceStacksStore } from '../deviceStacks'
import { useDevicesStore } from '../devices'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('deviceStacks store', () => {
  it('ensureLoaded() не перечитывает уже загруженный список — поэтому после изменений нужен reload()', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchMock)
    const store = useDeviceStacksStore()
    store.loaded = true

    await store.ensureLoaded()

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reloadWithDevices() перечитывает и стеки, и реестр устройств', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        urls.push(url)
        if (url.includes('/resources/device-stacks')) {
          return jsonResponse({ items: [{ id: 's-1', name: 'Стек', description: null }], total: 1, offset: 0, limit: 1000 })
        }
        return jsonResponse({ items: [], total: 0 })
      }),
    )
    const stacks = useDeviceStacksStore()
    const devices = useDevicesStore()
    devices.loaded = true

    await stacks.reloadWithDevices()

    expect(stacks.all.map((s) => s.id)).toEqual(['s-1'])
    expect(urls.some((u) => u.includes('/resources/device-stacks'))).toBe(true)
    expect(urls.some((u) => /\/devices(\?|$)/.test(u))).toBe(true)
  })

  it('ошибка загрузки стеков попадает в store.error, а не пробрасывается исключением', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Сбой сервера' }, 500)),
    )
    const stacks = useDeviceStacksStore()

    await expect(stacks.reloadWithDevices()).resolves.toBeUndefined()

    expect(stacks.error).toBeTruthy()
  })
})
