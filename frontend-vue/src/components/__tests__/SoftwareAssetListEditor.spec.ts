import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SoftwareAssetListEditor from '../SoftwareAssetListEditor.vue'
import type { CatalogItem, SoftwareAssetDraftRow } from '../../api/types'

const catalog: CatalogItem[] = [
  { id: 'sa-1c', name: '1С:Предприятие' },
  { id: 'sa-ad', name: 'Active Directory' },
]

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
})

describe('SoftwareAssetListEditor.vue', () => {
  it('показывает подсказку, если программные активы не добавлены', () => {
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Программные активы не добавлены')
  })

  it('добавляет пустую строку по клику на "+ Программный актив"', async () => {
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ software_asset_id: '', version: '' }])
  })

  it('обновляет выбранный актив из справочника', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ software_asset_id: '', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    // Поле ПО — SearchableSelect (поиск вводом текста), не нативный <select>.
    expect(wrapper.find('.col-asset select').exists()).toBe(false)
    const input = wrapper.find('.col-asset .searchable-select input')
    expect(input.attributes('placeholder')).toBe('— выберите ПО —')
    await input.trigger('focus')
    const options = wrapper.findAll('.col-asset .ss-option')
    expect(options.map((o) => o.text())).toEqual(['1С:Предприятие', 'Active Directory'])
    await options[1].trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as SoftwareAssetDraftRow[])[0].software_asset_id).toBe('sa-ad')
  })

  it('поиск вводом текста фильтрует список ПО без учёта регистра', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ software_asset_id: '', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    const input = wrapper.find('.col-asset .searchable-select input')
    await input.trigger('focus')
    await input.setValue('active')

    const options = wrapper.findAll('.col-asset .ss-option')
    expect(options).toHaveLength(1)
    expect(options[0].text()).toBe('Active Directory')
  })

  it('показывает название уже выбранного ПО и снимает выбор крестиком', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ id: 'sw-1', software_asset_id: 'sa-1c', version: '8.3' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    expect(wrapper.find('.col-asset .searchable-select input').element).toHaveProperty('value', '1С:Предприятие')
    await wrapper.find('.col-asset .ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'sw-1', software_asset_id: '', version: '8.3' }])
  })

  it('обновляет версию, не мутируя исходный проп', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ id: 'sw-1', software_asset_id: 'sa-1c', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('input.col-version').setValue('8.3')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'sw-1', software_asset_id: 'sa-1c', version: '8.3' }])
    expect(rows[0].version).toBe('')
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: SoftwareAssetDraftRow[] = [
      { id: 'sw-1', software_asset_id: 'sa-1c', version: '8.3' },
      { id: 'sw-2', software_asset_id: 'sa-ad', version: '' },
    ]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })

  it('быстрое добавление программного актива подставляет его id в строку', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ software_asset_id: '', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/software-assets')) {
          return jsonResponse({ id: 'sa-new', name: 'GitLab' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.col-asset button').trigger('click')
    await teleportedContent().find('input[type="text"]').setValue('GitLab')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    const emitted = wrapper.emitted('update:modelValue')!
    const lastRows = emitted[emitted.length - 1][0] as SoftwareAssetDraftRow[]
    expect(lastRows[0].software_asset_id).toBe('sa-new')
  })
})
