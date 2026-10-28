// B-04: директива v-write-only скрывает элемент от ролей без права записи (authStore.canWrite).
import { describe, it, expect, beforeEach } from 'vitest'
import { defineComponent, h, nextTick, withDirectives } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vWriteOnly } from '../writeOnly'
import { useAuthStore } from '../../stores/auth'
import type { AuthUser } from '../../api/types'

const Host = defineComponent({
  render: () => h('div', [withDirectives(h('button', { class: 'write-btn' }, 'Добавить'), [[vWriteOnly]]), h('button', { class: 'read-btn' }, 'Обновить')]),
})

const viewer = { id: 'u1', username: 'v', role: 'viewer', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } as AuthUser

beforeEach(() => setActivePinia(createPinia()))

describe('v-write-only', () => {
  it('аутентификация выключена: элемент виден', () => {
    const wrapper = mount(Host)
    expect((wrapper.find('.write-btn').element as HTMLElement).style.display).toBe('')
  })

  it('viewer: элемент скрыт, соседние кнопки чтения не затронуты', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = viewer
    const wrapper = mount(Host)
    expect((wrapper.find('.write-btn').element as HTMLElement).style.display).toBe('none')
    expect((wrapper.find('.read-btn').element as HTMLElement).style.display).toBe('')
  })

  it('роль меняется на лету (выход/вход другим пользователем): видимость обновляется при перерисовке', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = viewer
    const wrapper = mount(Host)
    expect((wrapper.find('.write-btn').element as HTMLElement).style.display).toBe('none')

    auth.user = { ...viewer, role: 'admin' }
    await wrapper.vm.$forceUpdate()
    await nextTick()
    expect((wrapper.find('.write-btn').element as HTMLElement).style.display).toBe('')
  })
})
