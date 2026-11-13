// Хвост F-04 (код-ревью main): журнал аудита и экран VLAN тоже писали «Ничего не найдено по заданным фильтрам» при пустой базе.
// Теперь они, как остальные пять списков, различают два случая (общий ListEmptyState):
//   • журнал/реестр пуст — «пока нет» (у VLAN ещё и кнопка создания; у журнала её нет: записи пишет само приложение);
//   • записи есть, но поиск/фильтры ничего не оставили — «не найдено по заданным фильтрам» и «Сбросить фильтры».
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditLogView from '../AuditLogView.vue'
import VLANsView from '../VLANsView.vue'
import VLANFormModal from '../../components/VLANFormModal.vue'
import { useAuditLogStore } from '../../stores/auditLog'
import { useAuthStore } from '../../stores/auth'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useVLANsStore } from '../../stores/vlans'
import { auditJournal, auditServer } from '../../stores/__tests__/fixtures'
import type { AuthUser } from '../../api/types'

const SEARCH_DEBOUNCE_MS = 300 // как в AuditLogView

async function mountAudit(entries: number) {
  const server = auditServer(auditJournal(entries))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => new Response(JSON.stringify(server(url)))),
  )
  useCatalogsStore().loaded = true
  const wrapper = mount(AuditLogView)
  await flushPromises()
  return wrapper
}

function mountVlans(groups: ReturnType<typeof group>[]) {
  const vlans = useVLANsStore()
  vlans.groups = groups
  vlans.loaded = true
  useDevicesStore().loaded = true
  useCatalogsStore().loaded = true
  const wrapper = mount(VLANsView)
  return flushPromises().then(() => wrapper)
}

const group = (vlanId: number, name: string) => ({
  vlan_id: vlanId,
  definitions: [{ id: `v-${vlanId}`, vlan_id: vlanId, name, description: '', domain_id: null, domain_name: '', devices: [] }],
})

function asViewer() {
  const auth = useAuthStore()
  auth.enabled = true
  auth.user = {
    id: 'u1',
    username: 'viewer',
    role: 'viewer',
    is_active: true,
    last_login_at: null,
    locked: false,
    created_at: '2026-01-01T00:00:00',
  } as AuthUser
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('журнал аудита: пустое состояние', () => {
  it('журнал пуст: «пока нет записей», без слов про фильтры и без кнопок', async () => {
    const wrapper = await mountAudit(0)

    const cell = wrapper.get('td.empty-row')
    expect(cell.get('[data-empty="registry"]').text()).toBe('В журнале аудита пока нет записей.')
    expect(cell.text()).not.toContain('Ничего не найдено')
    expect(cell.find('button').exists()).toBe(false) // записи журнала пишет приложение — создавать нечего, сбрасывать нечего
  })

  it('записи есть, поиск ничего не нашёл: «не найдено по заданным фильтрам» и «Сбросить фильтры»', async () => {
    const wrapper = await mountAudit(5)
    const log = useAuditLogStore()
    expect(wrapper.findAll('tbody tr')).toHaveLength(5)

    log.search = 'нет такого текста'
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
    await flushPromises()

    const cell = wrapper.get('td.empty-row')
    expect(cell.get('[data-empty="filtered"]').text()).toBe('Ничего не найдено по заданным фильтрам.')
    expect(cell.text()).not.toContain('пока нет')
    expect(cell.get('[data-action="reset-filters"]').text()).toBe('Сбросить фильтры')
  })

  it('«Сбросить фильтры» очищает поиск и оба фильтра и возвращает записи', async () => {
    const wrapper = await mountAudit(5)
    const log = useAuditLogStore()
    log.search = 'нет такого текста'
    log.actionFilter = 'DELETE'
    log.entityTypeFilter = 'devices'
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
    await flushPromises()
    expect(wrapper.find('[data-empty="filtered"]').exists()).toBe(true)

    await wrapper.get('[data-action="reset-filters"]').trigger('click')
    expect([log.search, log.actionFilter, log.entityTypeFilter]).toEqual(['', 'all', ''])
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
    await flushPromises()

    expect(wrapper.find('td.empty-row').exists()).toBe(false)
    expect(wrapper.findAll('tbody tr')).toHaveLength(5)
  })
})

describe('экран VLAN: пустое состояние', () => {
  it('VLAN нет вовсе: «VLAN пока нет» и кнопка создания, про фильтры ни слова', async () => {
    const wrapper = await mountVlans([])

    const banner = wrapper.get('.empty-banner')
    expect(banner.get('[data-empty="registry"]').text()).toBe('VLAN пока нет.')
    expect(banner.text()).not.toContain('Ничего не найдено')
    expect(banner.find('[data-action="reset-filters"]').exists()).toBe(false)
    expect(banner.get('[data-action="create"]').text()).toBe('Добавить VLAN')
  })

  it('кнопка в пустом экране открывает ту же форму, что и кнопка в шапке', async () => {
    const wrapper = await mountVlans([])
    expect(wrapper.findComponent(VLANFormModal).exists()).toBe(false)

    await wrapper.get('.empty-banner [data-action="create"]').trigger('click')

    expect(wrapper.findComponent(VLANFormModal).exists()).toBe(true)
  })

  it('без права записи (viewer) кнопки создания нет, текст «пока нет» остаётся', async () => {
    asViewer()
    const wrapper = await mountVlans([])

    expect(wrapper.get('.empty-banner').text()).toContain('VLAN пока нет.')
    expect(wrapper.find('.empty-banner button').exists()).toBe(false)
  })

  it('VLAN есть, поиск ничего не нашёл: «не найдено по заданным фильтрам» и «Сбросить фильтры»', async () => {
    const wrapper = await mountVlans([group(10, 'Мониторинг')])
    useVLANsStore().search = 'нет такого'
    await flushPromises()

    const banner = wrapper.get('.empty-banner')
    expect(banner.get('[data-empty="filtered"]').text()).toBe('Ничего не найдено по заданным фильтрам.')
    expect(banner.text()).not.toContain('пока нет')
    expect(banner.find('[data-action="create"]').exists()).toBe(false)
  })

  it('«Сбросить фильтры» очищает поиск и возвращает список', async () => {
    const wrapper = await mountVlans([group(10, 'Мониторинг')])
    const vlans = useVLANsStore()
    vlans.search = 'нет такого'
    await flushPromises()

    await wrapper.get('[data-action="reset-filters"]').trigger('click')
    await flushPromises()

    expect(vlans.search).toBe('')
    expect(wrapper.find('.empty-banner').exists()).toBe(false)
    expect(wrapper.text()).toContain('Мониторинг')
  })
})
