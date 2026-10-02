import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditLogView from '../AuditLogView.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useAuditLogStore } from '../../stores/auditLog'
import type { AuditLogEntry } from '../../api/types'

function entries(count: number): AuditLogEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `a-${i}`,
    entity_type: 'devices',
    entity_id: `dev-${String(i).padStart(4, '0')}-xxxx`,
    action: 'UPDATE',
    details: `Запись ${i}`,
    created_at: new Date(Date.UTC(2026, 0, 1) + i * 60_000).toISOString(),
  }))
}

async function mountView(count: number) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: entries(count), total: count, offset: 0, limit: 1000 }))))
  const catalogs = useCatalogsStore()
  catalogs.loaded = true
  const wrapper = mount(AuditLogView)
  await flushPromises()
  return wrapper
}

const pageLabels = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.findAll('.pager button[aria-label^="Страница"]').map((b) => b.text())

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('AuditLogView.vue — пагинация', () => {
  it('при большом числе записей номера страниц собираются в окно, а не растягиваются на всю ширину', async () => {
    const wrapper = await mountView(1000) // 12 на странице → 84 страницы

    expect(pageLabels(wrapper)).toEqual(['1', '2', '84'])
    expect(wrapper.findAll('.pager button').length).toBeLessThan(10)
    expect(wrapper.find('.pager-gap').exists()).toBe(true)
  })

  it('переход по пейджеру меняет показанные записи, а окно номеров следует за страницей', async () => {
    const wrapper = await mountView(1000)

    await wrapper.find('.pager button[aria-label="Страница 84"]').trigger('click')

    expect(useAuditLogStore().page).toBe(84)
    expect(pageLabels(wrapper)).toEqual(['1', '83', '84'])
    expect(wrapper.findAll('tbody tr')).toHaveLength(4) // 1000 = 83·12 + 4
    expect(wrapper.find('.table-foot').text()).toContain('Показано 997–1000 из 1000')
  })

  it('«›» и «‹» листают по одной странице', async () => {
    const wrapper = await mountView(100)

    await wrapper.find('.pager button[aria-label="Следующая страница"]').trigger('click')
    expect(useAuditLogStore().page).toBe(2)
    await wrapper.find('.pager button[aria-label="Предыдущая страница"]').trigger('click')
    expect(useAuditLogStore().page).toBe(1)
  })

  it('смена фильтра возвращает на первую страницу, пейджер пересчитывается под отфильтрованное число записей', async () => {
    const wrapper = await mountView(1000)
    await wrapper.find('.pager button[aria-label="Страница 84"]').trigger('click')

    useAuditLogStore().search = 'Запись 9' // «Запись 9», 90–99, 900–999 — 111 записей, 10 страниц
    await flushPromises()

    expect(useAuditLogStore().page).toBe(1)
    expect(useAuditLogStore().filtered).toHaveLength(111)
    expect(pageLabels(wrapper)).toEqual(['1', '2', '10'])
  })

  it('одна страница записей — пейджер из одной кнопки, а не пустая полоса', async () => {
    const wrapper = await mountView(5)

    expect(pageLabels(wrapper)).toEqual(['1'])
  })
})
