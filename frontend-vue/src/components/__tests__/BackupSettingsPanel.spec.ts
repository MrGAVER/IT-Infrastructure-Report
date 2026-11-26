import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BackupSettingsPanel from '../BackupSettingsPanel.vue'
import { useToast } from '../../composables/useToast'
import { stubBackupSettingsApi } from '../../stores/__tests__/backupSettingsApi'
import { useBackupSettingsStore } from '../../stores/backupSettings'
import type { BackupSettings } from '../../api/types'

const field = (w: ReturnType<typeof mount>, name: 'interval' | 'keep') => w.find(`[data-testid="backup-${name}"]`)
const value = (w: ReturnType<typeof mount>, name: 'interval' | 'keep') => (field(w, name).element as HTMLInputElement).value
const save = (w: ReturnType<typeof mount>) => w.find('[data-testid="backup-save"]')
const reset = (w: ReturnType<typeof mount>) => w.find('[data-testid="backup-reset"]')
const text = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).text()

async function open() {
  const wrapper = mount(BackupSettingsPanel)
  await flushPromises()
  return wrapper
}

async function type(w: ReturnType<typeof mount>, name: 'interval' | 'keep', raw: string) {
  await field(w, name).setValue(raw)
}

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('BackupSettingsPanel.vue — показ', () => {
  it('поля заполнены действующими значениями, у каждого указан источник, каталог показан только для чтения', async () => {
    stubBackupSettingsApi({ interval_hours: 6, interval_source: 'settings', directory: 'D:\\RIS-backups', directory_source: 'environment' })

    const wrapper = await open()

    expect(value(wrapper, 'interval')).toBe('6')
    expect(value(wrapper, 'keep')).toBe('7')
    expect(text(wrapper, 'backup-interval-source')).toBe('задано в настройках')
    expect(text(wrapper, 'backup-keep-source')).toBe('значение по умолчанию')
    expect(text(wrapper, 'backup-current')).toContain('каждые 6 ч, хранить 7')
    expect(text(wrapper, 'backup-directory')).toContain('D:\\RIS-backups')
    expect(text(wrapper, 'backup-directory')).toContain('задан в окружении')
    expect(wrapper.find('[data-testid="backup-directory"] input').exists()).toBe(false)
  })

  it('без копий и попыток так и написано', async () => {
    stubBackupSettingsApi()

    const wrapper = await open()

    expect(text(wrapper, 'backup-latest')).toBe('копий ещё нет')
    expect(text(wrapper, 'backup-last-attempt')).toBe('с запуска приложения попыток не было')
  })

  it('последняя копия: время, имя файла и размер', async () => {
    stubBackupSettingsApi({ latest: { name: 'infra_registry.auto.20261123-120000.bak', size_bytes: 1536, created_at: '2026-11-23T12:00:00+00:00' } })

    const wrapper = await open()

    const latest = text(wrapper, 'backup-latest')
    expect(latest).toContain('23.11.2026')
    expect(latest).toContain('infra_registry.auto.20261123-120000.bak')
    expect(latest).toContain('1,5 КБ')
  })

  it.each<[string, BackupSettings['last_attempt'], string[]]>([
    ['создана копия', { at: '2026-11-23T12:00:00+00:00', ok: true, created: 'x.auto.bak', error: null }, ['создана копия', 'x.auto.bak']],
    ['копия не понадобилась', { at: '2026-11-23T12:00:00+00:00', ok: true, created: null, error: null }, ['копия не понадобилась', 'база не менялась']],
    ['ошибка', { at: '2026-11-23T12:00:00+00:00', ok: false, created: null, error: 'диск переполнен' }, ['ошибка:', 'диск переполнен']],
  ])('последняя попытка: %s', async (_name, attempt, fragments) => {
    stubBackupSettingsApi({ last_attempt: attempt })

    const wrapper = await open()

    for (const fragment of fragments) expect(text(wrapper, 'backup-last-attempt')).toContain(fragment)
  })

  it('планировщик не запущен при ненулевом интервале — об этом сказано; при нулевом — нет', async () => {
    stubBackupSettingsApi({ running: false })
    expect(text(await open(), 'backup-current')).toContain('планировщик не запущен')

    stubBackupSettingsApi({ running: false, interval_hours: 0 })
    const off = await open()
    expect(text(off, 'backup-current')).toContain('выключены')
    expect(text(off, 'backup-current')).not.toContain('планировщик не запущен')
  })

  it('PostgreSQL: вместо формы — подсказка про .env и README', async () => {
    stubBackupSettingsApi({
      supported: false,
      unsupported_reason: 'Плановые копии средствами приложения — только для SQLite; для PostgreSQL копии делает оператор СУБД.',
    })

    const wrapper = await open()

    const hint = text(wrapper, 'backup-unsupported')
    expect(hint).toContain('PostgreSQL')
    expect(hint).toContain('.env')
    expect(hint).toContain('Периодические резервные копии')
    expect(field(wrapper, 'interval').exists()).toBe(false)
    expect(save(wrapper).exists()).toBe(false)
  })

  it('ошибка загрузки (например, 403) показывается текстом сервера, формы нет', async () => {
    stubBackupSettingsApi({}, { loadStatus: 403 })

    const wrapper = await open()

    expect(text(wrapper, 'backup-load-error')).toBe('Настройки резервных копий доступны только администратору.')
    expect(field(wrapper, 'interval').exists()).toBe(false)
  })

  it('«Обновить статус» перечитывает настройки', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()
    const before = api.requests.length

    await wrapper.find('[data-testid="backup-refresh"]').trigger('click')
    await flushPromises()

    expect(api.requests.length).toBe(before + 1)
  })
})

describe('BackupSettingsPanel.vue — сохранение', () => {
  it('«Сохранить» недоступна, пока значения не изменены', async () => {
    stubBackupSettingsApi()

    const wrapper = await open()

    expect(save(wrapper).attributes('disabled')).toBeDefined()
  })

  it('отправляет оба изменённых параметра, показывает подтверждение и значения, которые вернул сервер', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()

    await type(wrapper, 'interval', '6')
    await type(wrapper, 'keep', '14')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.puts).toEqual([{ interval_hours: 6, keep: 14 }])
    expect(useToast().toasts.at(-1)?.message).toBe('Настройки резервных копий сохранены.')
    expect(text(wrapper, 'backup-interval-source')).toBe('задано в настройках')
    expect(text(wrapper, 'backup-current')).toContain('каждые 6 ч, хранить 14')
    expect(save(wrapper).attributes('disabled')).toBeDefined()
  })

  it('отправляет только изменённый параметр', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()

    await type(wrapper, 'keep', '30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.puts).toEqual([{ keep: 30 }])
  })

  it('дробный интервал с запятой отправляется числом', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()

    await type(wrapper, 'interval', '1,5')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.puts).toEqual([{ interval_hours: 1.5 }])
  })

  it.each([
    ['interval', '0.5', 'не меньше 1 ч'],
    ['interval', 'часто', 'число часов'],
    ['interval', '', 'Укажите интервал'],
    ['keep', '0', 'не меньше одной'],
    ['keep', '7.5', 'целое число'],
    ['keep', '999', 'не больше 365'],
  ] as const)('некорректное значение поля %s «%s» — ошибка под полем, запрос не уходит', async (name, raw, message) => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()

    await type(wrapper, name, raw)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(text(wrapper, `backup-${name}-error`)).toContain(message)
    expect(field(wrapper, name).attributes('aria-invalid')).toBe('true')
    expect(save(wrapper).attributes('disabled')).toBeDefined()
    expect(api.puts).toEqual([])
  })

  it('ошибка сервера показывается у кнопки, введённые значения не теряются', async () => {
    stubBackupSettingsApi({}, { saveStatus: 500 })
    const wrapper = await open()

    await type(wrapper, 'keep', '30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(text(wrapper, 'backup-save-error')).toBe('Сервер недоступен')
    expect(value(wrapper, 'keep')).toBe('30')
    expect(useToast().toasts.length).toBe(0)
  })

  it('интервал 0 просит подтверждение; отказ — запрос не уходит', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )

    await type(wrapper, 'interval', '0')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).toHaveBeenCalledOnce()
    expect(api.puts).toEqual([])
  })

  it('интервал 0 после подтверждения выключает копии', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()

    await type(wrapper, 'interval', '0')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).toHaveBeenCalledOnce()
    expect(api.puts).toEqual([{ interval_hours: 0 }])
    expect(text(wrapper, 'backup-current')).toContain('выключены')
  })
})

describe('BackupSettingsPanel.vue — параметры, заданные окружением', () => {
  it('поле недоступно, источник и причина названы, ввод не отправляется', async () => {
    const api = stubBackupSettingsApi({ keep: 30, keep_source: 'environment' })
    const wrapper = await open()

    expect(field(wrapper, 'keep').attributes('disabled')).toBeDefined()
    expect(text(wrapper, 'backup-keep-source')).toBe('задано в окружении')
    expect(text(wrapper, 'backup-keep-locked')).toContain('INFRA_REGISTRY_BACKUP_KEEP')

    await type(wrapper, 'interval', '6')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // заданный окружением параметр в запрос не попадает
    expect(api.puts).toEqual([{ interval_hours: 6 }])
  })

  it('значение, введённое до того, как параметр закрепили окружением, в запрос не попадает', async () => {
    const api = stubBackupSettingsApi()
    const wrapper = await open()
    await type(wrapper, 'interval', '6')
    await type(wrapper, 'keep', '30')

    const store = useBackupSettingsStore()
    store.settings = { ...store.settings!, interval_source: 'environment' } // например, оператор задал переменную, и статус перечитали
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.puts).toEqual([{ keep: 30 }])
  })

  it('если окружением заданы оба параметра, сохранять нечего', async () => {
    stubBackupSettingsApi({ interval_source: 'environment', keep_source: 'environment' })

    const wrapper = await open()

    expect(field(wrapper, 'interval').attributes('disabled')).toBeDefined()
    expect(field(wrapper, 'keep').attributes('disabled')).toBeDefined()
    expect(save(wrapper).attributes('disabled')).toBeDefined()
    expect(reset(wrapper).attributes('disabled')).toBeDefined()
  })
})

describe('BackupSettingsPanel.vue — сброс к умолчанию', () => {
  it('недоступен, пока всё по умолчанию', async () => {
    stubBackupSettingsApi()

    expect(reset(await open()).attributes('disabled')).toBeDefined()
  })

  it('сбрасывает только параметры, заданные в настройках, и возвращает умолчания', async () => {
    const api = stubBackupSettingsApi({ interval_hours: 6, interval_source: 'settings', keep: 30, keep_source: 'environment' })
    const wrapper = await open()

    await reset(wrapper).trigger('click')
    await flushPromises()

    // число копий задано окружением и не трогается
    expect(api.puts).toEqual([{ interval_hours: null }])
    expect(value(wrapper, 'interval')).toBe('24')
    expect(text(wrapper, 'backup-interval-source')).toBe('значение по умолчанию')
    expect(useToast().toasts.at(-1)?.message).toBe('Настройки резервных копий сброшены к значениям по умолчанию.')
  })
})
