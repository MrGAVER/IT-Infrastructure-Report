// Пункт 4 предложений по улучшению (ревью merge/review-f06-stage2-f05-executors): усечённая загрузка списка (потолок listAllResource)
// не должна быть видна только в toast, который гаснет через 10 с. Сторы запоминают truncated/total, а экраны, показывающие весь список
// (или считающие по нему числа), выводят постоянный DataLoadNotice.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContainersView from '../views/ContainersView.vue'
import DeviceStacksView from '../views/DeviceStacksView.vue'
import VLANDomainsPanel from '../components/VLANDomainsPanel.vue'
import ConnectionCanvasModal from '../components/ConnectionCanvasModal.vue'
import BuildingsView from '../views/BuildingsView.vue'
import StructuralUnitsView from '../views/StructuralUnitsView.vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useContainersStore } from '../stores/containers'
import { useDeviceStacksStore } from '../stores/deviceStacks'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useConnectionsStore } from '../stores/connections'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }
const json = (body: unknown) => new Response(JSON.stringify(body))

/** Сервер обещает 2 000 записей, но на вторую страницу отвечает пустой — загрузка прерывается усечённой (truncated). */
function stubTruncatedServer() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
      return json({ items: offset === 0 ? [{ id: 'row-1' }] : [], total: 2000, offset, limit: 1000 })
    }),
  )
}
function stubCompleteServer() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ items: [{ id: 'row-1' }], total: 1, offset: 0, limit: 1000 })),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(EMPTY_PAGE)),
  )
})

describe('сторы запоминают, что список загружен не целиком', () => {
  const stores = [
    ['containers', useContainersStore],
    ['vlanDomains', useVLANDomainsStore],
    ['deviceStacks', useDeviceStacksStore],
    ['connections', useConnectionsStore],
  ] as const

  it.each(stores)('%s: усечённая загрузка → truncated и total сервера; после полной перезагрузки признак снимается', async (_name, useStore) => {
    const store = useStore()
    expect(store.truncated).toBe(false)

    stubTruncatedServer()
    await store.reload()
    expect(store.truncated).toBe(true)
    expect(store.total).toBe(2000)
    expect(store.all).toHaveLength(1)

    stubCompleteServer()
    await store.reload()
    expect(store.truncated).toBe(false)
    expect(store.total).toBe(1)
  })
})

describe('экраны показывают постоянное сообщение о неполных данных', () => {
  const notice = (wrapper: { find: (s: string) => { exists(): boolean; text(): string; attributes(n: string): string | undefined } }) =>
    wrapper.find('.load-notice')
  const plain = (text: string) => text.replace(/\s+/g, ' ')

  it('ContainersView: «n из N» и пояснение про карточки; при полной загрузке сообщения нет', async () => {
    const store = useContainersStore()
    store.all = [{ id: 'c-1', name: 'nginx', virtual_machine_id: 'vm-1', physical_device_id: null } as never]
    store.loaded = true
    useDevicesStore().loaded = true
    useVMsStore().loaded = true
    store.total = 60000
    store.truncated = true

    const wrapper = mount(ContainersView)
    await flushPromises()
    expect(notice(wrapper).exists()).toBe(true)
    expect(notice(wrapper).attributes('data-kind')).toBe('incomplete')
    expect(plain(notice(wrapper).text())).toContain('загружено 1 из 60 000')
    expect(notice(wrapper).text()).toContain('Карточки ниже посчитаны только по загруженной части')

    store.truncated = false
    await flushPromises()
    expect(notice(wrapper).exists()).toBe(false)
  })

  it('DeviceStacksView', async () => {
    const store = useDeviceStacksStore()
    store.all = [{ id: 's-1', name: 'stack' } as never]
    store.loaded = true
    store.total = 2000
    store.truncated = true

    const wrapper = mount(DeviceStacksView)
    await flushPromises()
    expect(plain(notice(wrapper).text())).toContain('стеков устройств')
    expect(plain(notice(wrapper).text())).toContain('загружено 1 из 2 000')

    store.truncated = false
    await flushPromises()
    expect(notice(wrapper).exists()).toBe(false)
  })

  it('VLANDomainsPanel', async () => {
    const store = useVLANDomainsStore()
    store.all = [{ id: 'd-1', name: 'Ядро', description: null, source_device_id: null, auto_sync: false }]
    store.loaded = true
    store.total = 2000
    store.truncated = true
    useDevicesStore().loaded = true

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()
    expect(plain(notice(wrapper).text())).toContain('VLAN-доменов')

    store.truncated = false
    await flushPromises()
    expect(notice(wrapper).exists()).toBe(false)
  })

  it('ConnectionCanvasModal: схема рисует только загруженные подключения — об этом сказано', async () => {
    const store = useConnectionsStore()
    store.all = [{ id: 'k-1' } as never]
    store.loaded = true
    store.total = 2000
    store.truncated = true

    const wrapper = mount(ConnectionCanvasModal)
    await flushPromises()
    expect(plain(notice(wrapper).text())).toContain('подключений')
    expect(notice(wrapper).text()).toContain('На схеме нарисованы только они')

    store.truncated = false
    await flushPromises()
    expect(notice(wrapper).exists()).toBe(false)
  })
})

// B-02 (ревью merge/review-r1-r2-executors): справочники тоже могут не поместиться в потолок listAllResource. Стор запоминает это
// (incompleteCatalogs), а экраны, показывающие справочник целиком, выводят постоянное сообщение.
describe('экраны справочников показывают постоянное сообщение о неполных данных (B-02)', () => {
  const notices = (wrapper: { findAll: (s: string) => Array<{ text(): string; attributes(n: string): string | undefined }> }) => wrapper.findAll('.load-notice')
  const plain = (text: string) => text.replace(/\s+/g, ' ')

  /** Стор справочников уже загружен (сеть не нужна), усечение задаётся прямо в состоянии. */
  function seedCatalogs(incomplete: Record<string, { loaded: number; total: number }>) {
    const store = useCatalogsStore()
    store.loaded = true
    store.incompleteCatalogs = incomplete
    return store
  }

  it('StructuralUnitsView: «n из N» по структурным единицам; после полной загрузки сообщения нет', async () => {
    const store = seedCatalogs({ 'structural-units': { loaded: 3, total: 60000 } })

    const wrapper = mount(StructuralUnitsView)
    await flushPromises()

    expect(notices(wrapper)).toHaveLength(1)
    expect(notices(wrapper)[0].attributes('data-kind')).toBe('incomplete')
    expect(plain(notices(wrapper)[0].text())).toContain('структурных единиц')
    expect(plain(notices(wrapper)[0].text())).toContain('загружено 3 из 60 000')

    store.incompleteCatalogs = {}
    await flushPromises()
    expect(notices(wrapper)).toHaveLength(0)
  })

  it('BuildingsView: отдельное сообщение для каждого усечённого справочника (здания, помещения, стойки); чужие справочники не в счёт', async () => {
    seedCatalogs({
      buildings: { loaded: 1, total: 2000 },
      racks: { loaded: 5, total: 70000 },
      'structural-units': { loaded: 1, total: 9999 }, // не относится к этому экрану
    })

    const wrapper = mount(BuildingsView)
    await flushPromises()

    const texts = notices(wrapper).map((n) => plain(n.text()))
    expect(texts).toHaveLength(2)
    expect(texts[0]).toContain('зданий')
    expect(texts[0]).toContain('загружено 1 из 2 000')
    expect(texts[1]).toContain('стоек')
    expect(texts[1]).toContain('загружено 5 из 70 000')
    expect(texts.join(' ')).not.toContain('помещений')
  })

  it('BuildingsView: полная загрузка — сообщений нет', async () => {
    seedCatalogs({})

    const wrapper = mount(BuildingsView)
    await flushPromises()

    expect(notices(wrapper)).toHaveLength(0)
  })
})
