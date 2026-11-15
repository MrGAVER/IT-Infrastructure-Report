import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditSettingsModal from '../AuditSettingsModal.vue'
import { useToast } from '../../composables/useToast'
import { stubAuditSettingsApi } from '../../stores/__tests__/auditSettingsApi'

const input = (w: ReturnType<typeof mount>) => w.find('[data-field="retention-days"]')
const save = (w: ReturnType<typeof mount>) => w.find('[data-testid="audit-settings-save"]')
const reset = (w: ReturnType<typeof mount>) => w.find('[data-testid="audit-settings-reset"]')

async function open() {
  const wrapper = mount(AuditSettingsModal)
  await flushPromises()
  return wrapper
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

describe('AuditSettingsModal.vue', () => {
  it('диалог назван, поле заполнено текущим сроком, показаны статус и время последней очистки', async () => {
    stubAuditSettingsApi({ retention_days: 90, is_default: false, last_cleanup_at: '2026-11-14T10:00:00+00:00' })

    const wrapper = await open()

    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.attributes('aria-labelledby')).toBe('audit-settings-title')
    expect(wrapper.find('#audit-settings-title').text()).toBe('Настройки аудита')
    expect((input(wrapper).element as HTMLInputElement).value).toBe('90')
    expect(wrapper.find('[data-testid="audit-settings-current"]').text()).toBe('90 дн.')
    expect(wrapper.find('[data-testid="audit-settings-last-cleanup"]').text()).not.toContain('не выполнялась')
  })

  it('по умолчанию журнал не очищается: «не ограничен (значение по умолчанию)», очистка ещё не выполнялась, «Сохранить» и «Сбросить» недоступны', async () => {
    stubAuditSettingsApi()

    const wrapper = await open()

    expect((input(wrapper).element as HTMLInputElement).value).toBe('0')
    expect(wrapper.find('[data-testid="audit-settings-current"]').text()).toBe('не ограничен (значение по умолчанию)')
    expect(wrapper.find('[data-testid="audit-settings-last-cleanup"]').text()).toBe('ещё не выполнялась')
    expect(save(wrapper).attributes('disabled')).toBeDefined()
    expect(reset(wrapper).attributes('disabled')).toBeDefined()
  })

  it('пока настройки грузятся, видна загрузка, а формы нет', () => {
    stubAuditSettingsApi()
    const wrapper = mount(AuditSettingsModal)
    expect(wrapper.find('[data-testid="audit-settings-loading"]').exists()).toBe(true)
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('403 при загрузке: вместо формы текст сервера', async () => {
    stubAuditSettingsApi({}, { loadStatus: 403 })

    const wrapper = await open()

    expect(wrapper.find('[data-testid="audit-settings-load-error"]').text()).toContain('только администратору')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('сохраняет новый срок после подтверждения, сообщает об удалённых записях, закрывает окно и отдаёт итог родителю', async () => {
    const api = stubAuditSettingsApi({}, { removedNow: 7 })
    const wrapper = await open()

    await input(wrapper).setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('старше 30 дн.'))
    expect(api.puts).toEqual([{ retention_days: 30 }])
    expect(wrapper.emitted('saved')?.[0][0]).toMatchObject({ retention_days: 30, removed_now: 7 })
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'success', message: 'Настройки аудита сохранены. Удалено записей: 7.' })
  })

  it('отказ в подтверждении ничего не отправляет и не закрывает окно', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const api = stubAuditSettingsApi()
    const wrapper = await open()

    await input(wrapper).setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.puts).toEqual([])
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('срок 0 (не удалять) подтверждения не требует: данные не теряются', async () => {
    const api = stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const wrapper = await open()

    await input(wrapper).setValue('0')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).not.toHaveBeenCalled()
    expect(api.puts).toEqual([{ retention_days: 0 }])
    expect(useToast().toasts.at(-1)?.message).toBe('Настройки аудита сохранены.')
  })

  it.each([
    ['-1', 'целое число'],
    ['2.5', 'целое число'],
    ['abc', 'Укажите срок'], // в <input type="number"> буквы не вводятся: браузер (и jsdom) отдаёт пустое значение
    ['', 'Укажите срок'],
    ['3651', 'не может быть больше 3650'],
  ])('значение %j не уходит на сервер: «Сохранить» недоступна, причина показана', async (value, reason) => {
    const api = stubAuditSettingsApi()
    const wrapper = await open()

    await input(wrapper).setValue(value)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(save(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="audit-settings-field-error"]').text()).toContain(reason)
    expect(api.puts).toEqual([])
  })

  it('значение, равное текущему, не сохраняется (нечего менять)', async () => {
    stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const wrapper = await open()

    await input(wrapper).setValue('90')

    expect(save(wrapper).attributes('disabled')).toBeDefined()
  })

  it('«Сбросить» возвращает значение по умолчанию (null) и доступна, только если срок задан в форме', async () => {
    const api = stubAuditSettingsApi({ retention_days: 90, is_default: false })
    const wrapper = await open()
    expect(reset(wrapper).attributes('disabled')).toBeUndefined()

    await reset(wrapper).trigger('click')
    await flushPromises()

    expect(api.puts).toEqual([{ retention_days: null }])
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(confirm).not.toHaveBeenCalled() // умолчание — 0: ничего не удалится
  })

  it('сброс к умолчанию, которое удаляет записи (по умолчанию из окружения > 0), просит подтверждение', async () => {
    stubAuditSettingsApi({ retention_days: 0, is_default: false, default_retention_days: 60 })
    const wrapper = await open()

    await reset(wrapper).trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('старше 60 дн.'))
  })

  it('ошибка сервера при сохранении показана у кнопки: окно остаётся открытым, данные формы целы', async () => {
    stubAuditSettingsApi({}, { saveStatus: 403 })
    const wrapper = await open()

    await input(wrapper).setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-testid="audit-settings-save-error"]').text()).toContain('только администратору')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect((input(wrapper).element as HTMLInputElement).value).toBe('30')
  })

  it('срок сохранён, но очистка не удалась: предупреждение вместо «успеха»', async () => {
    stubAuditSettingsApi({}, { cleanupFailed: true })
    const wrapper = await open()

    await input(wrapper).setValue('30')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'warning' })
    expect(useToast().toasts.at(-1)?.message).toContain('очистка не удалась')
  })

  it('«Отмена» и крестик закрывают окно без запросов на сохранение', async () => {
    const api = stubAuditSettingsApi()
    const wrapper = await open()

    await wrapper.find('.modal-foot .btn-secondary').trigger('click')
    await wrapper.find('.icon-btn').trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(2)
    expect(api.puts).toEqual([])
  })
})
