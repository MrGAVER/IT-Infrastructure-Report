import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
})

describe('ConnectionFormModal.vue — быстрое добавление типа подключения', () => {
  it('подставляет id быстро добавленного типа подключения в форму', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['connection-types'] = []
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/connection-types')) {
          return jsonResponse({ id: 'ct-new', name: 'Оптоволокно' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    // .form-grid .lookup-row — сужаем от общего ".lookup-row button", т.к. теперь такие кнопки
    // есть ещё у выбора портов источника/назначения (кнопка "Управлять портами", см.
    // DevicePortsModal.vue) — без сужения find() мог бы вернуть не ту кнопку.
    await wrapper.find('.form-grid .lookup-row button').trigger('click') // "+" рядом с типом подключения
    await teleportedContent().find('input[type="text"]').setValue('Оптоволокно')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    const select = wrapper.find('.form-grid .lookup-row select')
    expect((select.element as HTMLSelectElement).value).toBe('ct-new')
  })
})

describe('ConnectionFormModal.vue — управление портами прямо из формы', () => {
  it('кнопка "Управлять портами" неактивна, пока устройство не выбрано', () => {
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const btn = wrapper.find('[aria-label="Управлять портами исходного устройства"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('открывает DevicePortsModal с меткой выбранного устройства и сбрасывает удалённый порт после сохранения', async () => {
    const catalogs = useCatalogsStore()
    catalogs.loaded = true // иначе DevicePortsModal.onMounted перезатрёт items['interfaces'] через reload()
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
        }
        // Сохранение портов в модалке удаляет единственный порт устройства.
        if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
          return jsonResponse({ items: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    const sourceDeviceSelect = sourceFieldset.find('select')
    const sourcePortSelect = sourceFieldset.findAll('select')[1]

    await sourceDeviceSelect.setValue('dev-1')
    await sourcePortSelect.setValue('if-1')
    expect((sourcePortSelect.element as HTMLSelectElement).value).toBe('if-1')

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(new DOMWrapper(document.body).text()).toContain('Порты устройства «srv-01»')

    await new DOMWrapper(document.body).find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    // Порт удалён в модалке -> в форме подключения выбор порта должен сброситься, а не
    // молча указывать на несуществующий id.
    expect((sourcePortSelect.element as HTMLSelectElement).value).toBe('')
    // Модалка портов закрылась сама после сохранения.
    expect(new DOMWrapper(document.body).text()).not.toContain('Порты устройства')
  })
})
