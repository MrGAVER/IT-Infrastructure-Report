import { describe, it, expect, vi } from 'vitest'
import {
  createReportTemplate,
  deleteReportTemplate,
  duplicateReportTemplate,
  generateReportFromTemplate,
  getReportTemplate,
  listReportTemplateVersions,
  listReportTemplates,
  renameReportTemplate,
  restoreReportTemplateVersion,
  saveReportTemplate,
} from '../reportTemplates'
import type { ReportTemplate } from '../types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const templateFixture: ReportTemplate = {
  id: 't-1',
  name: 'Реестр устройств',
  description: null,
  format: 'xlsx',
  config: { sheets: [{ title: 'Лист 1', columns: [{ width: 20 }], rows: [] }] },
  created_at: null,
  updated_at: null,
}

describe('listReportTemplates / getReportTemplate', () => {
  it('listReportTemplates запрашивает GET /report-templates и возвращает голый массив (без items/total)', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse([templateFixture]))
    vi.stubGlobal('fetch', fetchMock)
    const result = await listReportTemplates()
    expect(result).toEqual([templateFixture])
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates')
  })

  it('getReportTemplate запрашивает конкретный шаблон по id', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture))
    vi.stubGlobal('fetch', fetchMock)
    expect(await getReportTemplate('t-1')).toEqual(templateFixture)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1')
  })
})

describe('createReportTemplate', () => {
  it('xlsx — заводит минимальный валидный каркас: один лист/колонка/строка с названием', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createReportTemplate({ name: 'Новый отчёт', description: 'описание', format: 'xlsx' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates')
    const body = JSON.parse(init!.body as string)
    expect(body).toMatchObject({ name: 'Новый отчёт', description: 'описание', format: 'xlsx' })
    expect(body.config).toEqual({
      sheets: [
        { title: 'Новый отчёт', columns: [{ width: 30 }], rows: [{ height: 20, repeat: false, cells: [{ col: 0, kind: 'static', text: 'Новый отчёт' }] }] },
      ],
    })
  })

  it('docx — заводит один блок-заголовок с названием', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ ...templateFixture, format: 'docx' }, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createReportTemplate({ name: 'Word-отчёт', description: null, format: 'docx' })

    const body = JSON.parse(fetchMock.mock.calls[0][1]!.body as string)
    expect(body.config).toEqual({ blocks: [{ type: 'heading', text: 'Word-отчёт' }] })
  })

  it('название длиннее 31 символа (лимит имени листа Excel) обрезается в заголовке листа, но не в самом названии шаблона', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture, 201))
    vi.stubGlobal('fetch', fetchMock)
    const longName = 'Очень длинное название шаблона отчёта, которое точно длиннее лимита'

    await createReportTemplate({ name: longName, description: null, format: 'xlsx' })

    const body = JSON.parse(fetchMock.mock.calls[0][1]!.body as string)
    expect(body.name).toBe(longName)
    expect((body.config.sheets[0].title as string).length).toBeLessThanOrEqual(31)
  })
})

describe('renameReportTemplate', () => {
  it('отправляет PUT с новыми name/description, но округляет format/config из переданного шаблона неизменными', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture))
    vi.stubGlobal('fetch', fetchMock)

    await renameReportTemplate(templateFixture, { name: 'Переименован', description: 'новое описание' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates/t-1')
    expect(init?.method).toBe('PUT')
    const body = JSON.parse(init!.body as string)
    expect(body).toEqual({ name: 'Переименован', description: 'новое описание', format: 'xlsx', config: templateFixture.config })
  })
})

describe('прочие операции жизненного цикла', () => {
  it('deleteReportTemplate — DELETE по id', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    await deleteReportTemplate('t-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('duplicateReportTemplate — POST .../duplicate без тела', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture, 201))
    vi.stubGlobal('fetch', fetchMock)
    await duplicateReportTemplate('t-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1/duplicate')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST')
  })

  it('listReportTemplateVersions — GET .../versions', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      jsonResponse([{ id: 'v-1', version_number: 1, name: 'x', description: null, format: 'xlsx', created_at: null }]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const versions = await listReportTemplateVersions('t-1')
    expect(versions).toHaveLength(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1/versions')
  })

  it('restoreReportTemplateVersion — POST .../versions/{id}/restore', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture))
    vi.stubGlobal('fetch', fetchMock)
    await restoreReportTemplateVersion('t-1', 'v-2')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1/versions/v-2/restore')
  })

  it('generateReportFromTemplate — POST .../generate без параметров', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ file_name: 'x.xlsx', download_url: '/api/v1/reports/download/x.xlsx' }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await generateReportFromTemplate('t-1')
    expect(result.file_name).toBe('x.xlsx')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-templates/t-1/generate')
  })
})

describe('saveReportTemplate', () => {
  it('id === null -> POST /report-templates (создание)', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture, 201))
    vi.stubGlobal('fetch', fetchMock)

    await saveReportTemplate(null, { name: 'Новый', description: null, format: 'xlsx', config: { sheets: [] } })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates')
    expect(init?.method).toBe('POST')
  })

  it('id задан -> PUT /report-templates/{id} (сохранение отредактированного содержимого)', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture))
    vi.stubGlobal('fetch', fetchMock)

    const config = { sheets: [{ title: 'Лист 1', columns: [{ width: 20 }], rows: [] }] }
    await saveReportTemplate('t-1', { name: 'Реестр устройств', description: null, format: 'xlsx', config })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates/t-1')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init!.body as string).config).toEqual(config)
  })
})
