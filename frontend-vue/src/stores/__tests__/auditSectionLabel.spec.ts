// Контракт «раздел журнала аудита ↔ подпись во frontend». Записи об изменении срока хранения и об очистке сервер пишет в раздел
// AUDIT_ENTITY (backend/app/services/audit_retention.py). Этого раздела нет в /api/v1/resources, поэтому подпись для него задана
// во frontend (stores/catalogs.ts), и переименование константы на сервере молча оставило бы в журнале сырое имя раздела.
//
// Как и backendPathReferences.spec.ts, тест пропускается, если рядом нет каталога backend (frontend собирают отдельно).
import { beforeEach, describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'
import { useCatalogsStore } from '../catalogs'
import { srcDir } from '../../__tests__/sourceFiles'

const auditRetentionModule = join(resolve(srcDir, '../..'), 'backend', 'app', 'services', 'audit_retention.py')

beforeEach(() => setActivePinia(createPinia()))

describe.skipIf(!existsSync(auditRetentionModule))('раздел журнала аудита для настроек аудита: backend ↔ frontend', () => {
  const entity = /^AUDIT_ENTITY\s*=\s*["']([^"']+)["']/m.exec(existsSync(auditRetentionModule) ? readFileSync(auditRetentionModule, 'utf-8') : '')?.[1]

  it('константа AUDIT_ENTITY находится в backend/app/services/audit_retention.py (иначе проверка ничего не проверяет)', () => {
    expect(entity).toBeTruthy()
  })

  it('у раздела из AUDIT_ENTITY есть подпись, а не сырое имя', () => {
    const store = useCatalogsStore() // справочники не загружены: подпись берётся из служебных разделов, а не из /resources

    expect(store.resourceLabel(entity!)).toBe('Настройки аудита')
  })
})
