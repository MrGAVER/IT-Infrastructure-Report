// ИБ-02 (ревью merge/review-r3-executors): единый помощник «сохранить blob». Ссылка освобождается с задержкой, а не сразу после click():
// в части браузеров немедленный revokeObjectURL обрывает загрузку.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BLOB_URL_REVOKE_DELAY_MS, saveBlob } from '../saveBlob'

// Привязывается до подмены document.createElement: иначе подмена вызывала бы саму себя.
const nativeCreateElement = document.createElement.bind(document)

describe('saveBlob', () => {
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>
  let anchors: HTMLAnchorElement[]

  /** Подменяет click() у создаваемых ссылок (в jsdom он пытался бы навигировать) и запоминает их для проверок. */
  function stubAnchors(click: () => void = () => {}): void {
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = nativeCreateElement(tag)
      if (tag === 'a') {
        el.click = vi.fn(click)
        anchors.push(el as HTMLAnchorElement)
      }
      return el
    }) as typeof document.createElement)
  }

  beforeEach(() => {
    vi.useFakeTimers()
    createObjectURL = vi.fn(() => 'blob:mock')
    revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    anchors = []
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('скачивает blob под заданным именем: ссылка на blob, атрибут download, один клик', () => {
    stubAnchors()
    const blob = new Blob(['x'])

    saveBlob(blob, 'Диаграмма.svg')

    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(anchors).toHaveLength(1)
    expect(anchors[0].href).toBe('blob:mock')
    expect(anchors[0].download).toBe('Диаграмма.svg')
    expect(anchors[0].click).toHaveBeenCalledTimes(1)
  })

  it('служебная ссылка не остаётся в документе после клика', () => {
    stubAnchors()

    saveBlob(new Blob(['x']), 'a.svg')

    expect(document.body.contains(anchors[0])).toBe(false)
  })

  it('blob-ссылка освобождается не сразу, а по истечении задержки', () => {
    stubAnchors()

    saveBlob(new Blob(['x']), 'a.svg')

    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(BLOB_URL_REVOKE_DELAY_MS - 1)
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })

  it('если click() бросил исключение, ссылка всё равно убирается из документа и освобождается по таймеру', () => {
    stubAnchors(() => {
      throw new Error('click failed')
    })

    expect(() => saveBlob(new Blob(['x']), 'bad.svg')).toThrow('click failed')

    expect(document.body.contains(anchors[0])).toBe(false)
    vi.advanceTimersByTime(BLOB_URL_REVOKE_DELAY_MS)
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
  })
})
