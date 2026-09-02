import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsView from '../SettingsView.vue'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../../stores/organization'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('SettingsView.vue', () => {
  it('поле по умолчанию предзаполнено текущим наименованием организации', () => {
    const wrapper = mount(SettingsView)
    expect((wrapper.find('.org-name-row input').element as HTMLInputElement).value).toBe(DEFAULT_ORGANIZATION_NAME)
  })

  it('сохраняет новое наименование в стор по клику на "Сохранить"', async () => {
    const wrapper = mount(SettingsView)
    const organization = useOrganizationStore()

    await wrapper.find('.org-name-row input').setValue('ООО «Ромашка»')
    await wrapper.find('.org-name-row button.btn-primary').trigger('click')

    expect(organization.name).toBe('ООО «Ромашка»')
    expect(wrapper.find('.current').text()).toContain('Сохранено')
  })

  it('"Сбросить" возвращает значение по умолчанию', async () => {
    const organization = useOrganizationStore()
    organization.setName('ООО «Ромашка»')
    const wrapper = mount(SettingsView)

    await wrapper.find('.org-name-row button.btn-secondary').trigger('click')

    expect(organization.name).toBe(DEFAULT_ORGANIZATION_NAME)
    expect((wrapper.find('.org-name-row input').element as HTMLInputElement).value).toBe(DEFAULT_ORGANIZATION_NAME)
  })
})
