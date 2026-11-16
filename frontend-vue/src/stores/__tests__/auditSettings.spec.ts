import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuditSettingsStore } from '../auditSettings'
import { stubAuditSettingsApi } from './auditSettingsApi'

beforeEach(() => setActivePinia(createPinia()))

describe('stores/auditSettings', () => {
  it('load читает настройки с сервера', async () => {
    stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const store = useAuditSettingsStore()

    await store.load()

    expect(store.settings?.retention_days).toBe(90)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('ошибка загрузки (403 у viewer) остаётся текстом сервера, настройки не появляются', async () => {
    stubAuditSettingsApi({}, { loadStatus: 403 })
    const store = useAuditSettingsStore()

    await store.load()

    expect(store.settings).toBeNull()
    expect(store.error).toBe('Журнал аудита доступен только администратору.')
  })

  it('save отправляет срок и запоминает подтверждённые сервером настройки; итог очистки отдаёт вызывающему', async () => {
    const api = stubAuditSettingsApi({}, { removedNow: 12 })
    const store = useAuditSettingsStore()

    const result = await store.save(30)

    expect(api.puts).toEqual([{ retention_days: 30 }])
    expect(result.removed_now).toBe(12)
    expect(store.settings).toEqual({ retention_days: 30, is_default: false, default_retention_days: 0, max_retention_days: 3650, last_cleanup_at: null })
    expect(store.saving).toBe(false)
  })

  it('save(null) сбрасывает к умолчанию', async () => {
    const api = stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const store = useAuditSettingsStore()

    await store.save(null)

    expect(api.puts).toEqual([{ retention_days: null }])
    expect(store.settings?.is_default).toBe(true)
  })

  it('ошибка сохранения пробрасывается, а прежние настройки не затираются', async () => {
    stubAuditSettingsApi({ retention_days: 90, is_default: false }, { saveStatus: 403 })
    const store = useAuditSettingsStore()
    await store.load()

    await expect(store.save(1)).rejects.toThrow('Журнал аудита доступен только администратору.')

    expect(store.settings?.retention_days).toBe(90)
    expect(store.saving).toBe(false)
  })
})
