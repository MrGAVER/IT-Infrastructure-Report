import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Sidebar from '../Sidebar.vue'
import { useOrganizationStore } from '../../stores/organization'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('Sidebar.vue', () => {
  it('по умолчанию показывает "ООО «Организация»"', () => {
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.find('.brand-text span').text()).toBe('ООО «Организация»')
  })

  // Регресс на п.6: раньше строка была захардкожена в шаблоне, а не в сторе — изменить
  // наименование можно было только правкой исходников.
  it('отображает наименование организации, заданное в настройках (stores/organization.ts)', () => {
    const organization = useOrganizationStore()
    organization.setName('ООО «Ромашка»')
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.find('.brand-text span').text()).toBe('ООО «Ромашка»')
  })

  // п.6: пункт меню "Другие справочники", ведущий на новый OtherCatalogsView.vue.
  it('содержит пункт меню "Другие справочники"', () => {
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a :href="to"><slot /></a>', props: ['to'] } } },
    })
    const link = wrapper.findAll('a').find((a) => a.text().includes('Другие справочники'))
    expect(link?.attributes('href')).toBe('/other-catalogs')
  })
})
