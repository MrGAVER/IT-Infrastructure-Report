import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../organization'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('useOrganizationStore', () => {
  it('по умолчанию — значение из хардкода шапки, который заменяет этот стор', () => {
    const org = useOrganizationStore()
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
    expect(org.name).toBe('ООО «Организация»')
  })

  it('устанавливает новое наименование и обрезает пробелы по краям', () => {
    const org = useOrganizationStore()
    org.setName('  ООО «Ромашка»  ')
    expect(org.name).toBe('ООО «Ромашка»')
  })

  it('пустое или пробельное имя откатывается на значение по умолчанию', () => {
    const org = useOrganizationStore()
    org.setName('   ')
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
  })

  it('сохраняет выбор в localStorage и восстанавливает при следующей инициализации стора', () => {
    const org = useOrganizationStore()
    org.setName('ООО «Ромашка»')
    expect(localStorage.getItem('itr.organizationName')).toBe('ООО «Ромашка»')

    setActivePinia(createPinia())
    const org2 = useOrganizationStore()
    expect(org2.name).toBe('ООО «Ромашка»')
  })

  it('reset() возвращает значение по умолчанию', () => {
    const org = useOrganizationStore()
    org.setName('ООО «Ромашка»')
    org.reset()
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
    expect(localStorage.getItem('itr.organizationName')).toBe(DEFAULT_ORGANIZATION_NAME)
  })
})
