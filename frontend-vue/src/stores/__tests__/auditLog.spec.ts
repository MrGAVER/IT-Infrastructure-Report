import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuditLogStore } from '../auditLog'
import { auditLogFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(auditLogFixture))))
})

describe('useAuditLogStore', () => {
  it('загружает записи и сортирует по дате — новые сверху', async () => {
    const store = useAuditLogStore()
    await store.ensureLoaded()
    expect(store.total).toBe(3)
    expect(store.all.map((e) => e.id)).toEqual(['a-3', 'a-2', 'a-1'])
  })

  it('фильтрует по подстроке (детали/id записи)', async () => {
    const store = useAuditLogStore()
    await store.ensureLoaded()

    store.search = 'Изменено'
    expect(store.filtered.map((e) => e.id)).toEqual(['a-2'])

    store.search = 'dev-1'
    expect(store.filtered.map((e) => e.id).sort()).toEqual(['a-1', 'a-2'])
  })

  it('фильтрует по действию и разделу', async () => {
    const store = useAuditLogStore()
    await store.ensureLoaded()

    store.actionFilter = 'DELETE'
    expect(store.filtered.map((e) => e.id)).toEqual(['a-3'])
    store.actionFilter = 'all'

    store.entityTypeFilter = 'information-systems'
    expect(store.filtered.map((e) => e.id)).toEqual(['a-3'])
  })

  it('entityTypesInUse — только реально встречающиеся разделы, без дублей', async () => {
    const store = useAuditLogStore()
    await store.ensureLoaded()
    expect(store.entityTypesInUse).toEqual(['devices', 'information-systems'])
  })
})
