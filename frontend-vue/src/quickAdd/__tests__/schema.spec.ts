import { describe, expect, it } from 'vitest'
import { QUICK_ADD_FIELDS, QUICK_ADD_LABELS } from '../schema'

describe('QUICK_ADD_FIELDS', () => {
  // Фикс п.4.4: "поле 'Версия' есть и в блоке 'Программные активы' на форме, и во всплывающем
  // окне 'Добавить: Программный актив' — поля дублируют друг друга". Версия по месту установки —
  // отдельное поле на связи (VMSoftware.version / DeviceSoftware.version), которое и остаётся
  // редактируемым построчно в SoftwareAssetListEditor.vue (см. её .col-version); версия у самого
  // каталога (SoftwareAsset.version) не имеет смысла при SoftwareAsset.name UNIQUE — один и тот
  // же продукт может быть установлен в разных версиях на разных устройствах.
  it('каталог "Программный актив" не запрашивает версию — она задаётся только по месту установки', () => {
    const fieldNames = QUICK_ADD_FIELDS['software-assets'].map((f) => f.name)
    expect(fieldNames).not.toContain('version')
    expect(fieldNames).toEqual(['name', 'category', 'vendor', 'description'])
  })

  // Фикс п.4: "непонятно зачем используется справочник 'Организация'. Если он не используется,
  // то нужно его удалить" — на organizations нигде не было ни одной FK-ссылки (см. миграцию
  // e519c184f3ae, backend/app/models.py), справочник целиком удалён из UI и из БД.
  it('справочник "organizations" удалён — ни на что не ссылался по FK', () => {
    expect(QUICK_ADD_FIELDS).not.toHaveProperty('organizations')
    expect(QUICK_ADD_LABELS).not.toHaveProperty('organizations')
  })
})
