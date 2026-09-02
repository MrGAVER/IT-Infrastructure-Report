import { describe, it, expect, vi } from 'vitest'
import { useOverlayDismiss } from '../useOverlayDismiss'

function mouseEvent(target: EventTarget, currentTarget: EventTarget): MouseEvent {
  const event = new MouseEvent('click')
  Object.defineProperty(event, 'target', { value: target })
  Object.defineProperty(event, 'currentTarget', { value: currentTarget })
  return event
}

describe('useOverlayDismiss', () => {
  it('закрывает модалку по обычному клику на подложку (mousedown и click на одном элементе)', () => {
    const overlay = document.createElement('div')
    const onDismiss = vi.fn()
    const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(onDismiss)

    onOverlayPointerDown(mouseEvent(overlay, overlay))
    onOverlayClick(mouseEvent(overlay, overlay))

    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it('НЕ закрывает модалку, если mousedown был внутри карточки, а click (из-за выделения текста) долетел до подложки', () => {
    const overlay = document.createElement('div')
    const cardText = document.createElement('span')
    const onDismiss = vi.fn()
    const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(onDismiss)

    // mousedown — внутри карточки (пользователь начинает выделять текст)
    onOverlayPointerDown(mouseEvent(cardText, overlay))
    // click — браузер дошёл до общего предка (подложки), т.к. mouseup случился за пределами карточки
    onOverlayClick(mouseEvent(overlay, overlay))

    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('НЕ закрывает модалку по клику внутри самой карточки (event.target !== currentTarget)', () => {
    const overlay = document.createElement('div')
    const cardText = document.createElement('span')
    const onDismiss = vi.fn()
    const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(onDismiss)

    onOverlayPointerDown(mouseEvent(cardText, overlay))
    onOverlayClick(mouseEvent(cardText, overlay))

    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('сбрасывает состояние после клика — следующий обычный клик по подложке продолжает работать', () => {
    const overlay = document.createElement('div')
    const cardText = document.createElement('span')
    const onDismiss = vi.fn()
    const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(onDismiss)

    onOverlayPointerDown(mouseEvent(cardText, overlay)) // "неудавшееся" выделение
    onOverlayClick(mouseEvent(overlay, overlay))
    expect(onDismiss).not.toHaveBeenCalled()

    onOverlayPointerDown(mouseEvent(overlay, overlay)) // обычный клик по подложке
    onOverlayClick(mouseEvent(overlay, overlay))
    expect(onDismiss).toHaveBeenCalledOnce()
  })
})
