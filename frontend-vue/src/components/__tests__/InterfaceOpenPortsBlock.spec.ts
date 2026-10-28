import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import InterfaceOpenPortsBlock from '../InterfaceOpenPortsBlock.vue'
import OpenPortListEditor from '../OpenPortListEditor.vue'
import type { OpenPortDraftRow } from '../../api/types'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'

const catalog = [{ id: 'c80', port: 80, protocol_type: 'HTTP', description: null }]
const http: OpenPortDraftRow = { protocol_catalog_id: 'c80', transport_protocol: 'tcp', description: '' }
const rows = [makeRow({ id: 'a', name: 'Gi0/1', open_ports: [http] }), makeRow({ id: 'b', name: 'Gi0/2' }), makeRow({ name: '' })]

function mountBlock(props: Partial<InstanceType<typeof InterfaceOpenPortsBlock>['$props']> = {}) {
  return mount(InterfaceOpenPortsBlock, {
    props: { rows, index: 0, catalogEntries: catalog, managed: false, lockNote: '', collapseAfter: 20, copyTarget: '', ...props },
    global: { plugins: [createPinia()] },
  })
}

describe('InterfaceOpenPortsBlock', () => {
  it('копировать можно на любой другой порт; безымянный получатель подписан номером строки', () => {
    const wrapper = mountBlock()

    const options = wrapper.findAll('.copy-target-select option').map((o) => [o.attributes('value'), o.text()])
    expect(options).toEqual([['', 'Скопировать на порт…'], ['1', 'Gi0/2'], ['2', '#3']])
  })

  it('выбор получателя уходит событием, выбранный показывается в списке', async () => {
    const wrapper = mountBlock()
    await wrapper.get('.copy-target-select').setValue('1')
    expect(wrapper.emitted('set-copy-target')![0]).toEqual(['1'])

    await wrapper.setProps({ copyTarget: '1' })
    expect((wrapper.get('.copy-target-select').element as HTMLSelectElement).value).toBe('1')
  })

  it('«Копировать» доступна, только когда выбран получатель и есть что копировать', async () => {
    const button = (w: ReturnType<typeof mountBlock>) => w.get('.copy-ports-row button')

    expect(button(mountBlock({ copyTarget: '' })).attributes('disabled')).toBeDefined()
    expect(button(mountBlock({ copyTarget: '1', index: 1 })).attributes('disabled')).toBeDefined() // у Gi0/2 открытых портов нет
    const ready = mountBlock({ copyTarget: '1' })
    expect(button(ready).attributes('disabled')).toBeUndefined()
    await button(ready).trigger('click')
    expect(ready.emitted('copy')).toHaveLength(1)
  })

  it('у единственного порта копировать некуда — блока копирования нет', () => {
    const wrapper = mountBlock({ rows: [rows[0]] })
    expect(wrapper.find('.copy-ports-row').exists()).toBe(false)
  })

  it('набор показывает редактор открытых портов этого порта; его изменение уходит событием', async () => {
    const wrapper = mountBlock()
    const editor = wrapper.getComponent(OpenPortListEditor)

    expect(editor.props('modelValue')).toEqual([http])
    expect(editor.props('catalogEntries')).toEqual(catalog)
    expect(editor.props('collapseAfter')).toBe(20)
    editor.vm.$emit('update:modelValue', [])
    expect(wrapper.emitted('update:openPorts')![0]).toEqual([[]])
  })

  it('набор задаёт группа: редактор только для просмотра, копирования нет, подсказка показана', () => {
    const wrapper = mountBlock({ managed: true, lockNote: 'Список открытых портов задан группой «Магистраль»' })

    expect(wrapper.getComponent(OpenPortListEditor).props('readonly')).toBe(true)
    expect(wrapper.find('.copy-ports-row').exists()).toBe(false)
    expect(wrapper.get('.group-lock').text()).toContain('«Магистраль»')
  })
})
