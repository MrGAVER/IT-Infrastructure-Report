import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportsView from '../ReportsView.vue'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useCatalogsStore } from '../../stores/catalogs'

const generateStructuralAppendixReport = vi.fn()
const downloadReport = vi.fn()

vi.mock('../../api/reports', () => ({
  generateInventoryReport: vi.fn(),
  generateAuditLogReport: vi.fn(),
  generateStructuralAppendixReport: (...args: unknown[]) => generateStructuralAppendixReport(...args),
  downloadReport: (...args: unknown[]) => downloadReport(...args),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  generateStructuralAppendixReport.mockReset()
  downloadReport.mockReset()
  generateStructuralAppendixReport.mockResolvedValue({ file_name: 'appendix.docx', download_url: '/api/v1/reports/download/appendix.docx' })
  downloadReport.mockResolvedValue(undefined)
  // Справочники и ИС считаем уже загруженными: тест проверяет сам экран, а не сетевые запросы при монтировании.
  useInformationSystemsStore().loaded = true
  useCatalogsStore().loaded = true
})

async function mountView() {
  const wrapper = mount(ReportsView, { global: { stubs: { 'router-link': true } } })
  await flushPromises()
  return wrapper
}

describe('ReportsView.vue — приложение к структурной схеме', () => {
  it('короткое имя ИС по умолчанию — «ЕАИС ТО» (и в поле, и в подсказке)', async () => {
    const wrapper = await mountView()

    const input = wrapper.find('input[maxlength="100"]')
    expect((input.element as HTMLInputElement).value).toBe('ЕАИС ТО')
    expect(input.attributes('placeholder')).toBe('ЕАИС ТО')
  })

  it('без правки поля на сервер уходит «ЕАИС ТО»', async () => {
    const wrapper = await mountView()

    await wrapper.findAll('section.report-card')[1].find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(generateStructuralAppendixReport).toHaveBeenCalledWith('ЕАИС ТО', [])
    expect(downloadReport).toHaveBeenCalledTimes(1)
  })

  it('введённое пользователем имя уходит как есть (обрезаются только пробелы по краям)', async () => {
    const wrapper = await mountView()

    await wrapper.find('input[maxlength="100"]').setValue('  ЕАИС Склад ')
    await wrapper.findAll('section.report-card')[1].find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(generateStructuralAppendixReport).toHaveBeenCalledWith('ЕАИС Склад', [])
  })

  it('пустое имя блокирует кнопку формирования', async () => {
    const wrapper = await mountView()

    await wrapper.find('input[maxlength="100"]').setValue('   ')

    expect(wrapper.findAll('section.report-card')[1].find('button.btn-primary').attributes('disabled')).toBeDefined()
  })
})
