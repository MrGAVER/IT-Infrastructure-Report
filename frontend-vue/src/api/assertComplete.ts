// B-02 (ревью merge/review-r1-r2-executors): список, который форма сохраняет ЦЕЛИКОМ (ПО, VLAN и порты устройства), нельзя брать из усечённой
// загрузки: сервер приводит список к присланному и удалил бы записи, которых форма не увидела. Загрузка в формах устройства идёт одним
// Promise.all и при любой ошибке помечает вложенные данные как не загруженные (useDeviceLoader: nestedLoadFailed) — поэтому «загружено не
// целиком» здесь превращается в ту же ошибку, а не в молчаливый обрезанный список.
//
// Отдельный модуль, а не часть client.ts: тесты api-модулей подменяют `../client` целиком, и помощник не должен зависеть от этой подмены.
import type { AllPagesResponse } from './client'

type CompletenessInfo = Pick<AllPagesResponse<unknown>, 'items' | 'total' | 'truncated'>

const formatCount = (n: number) => n.toLocaleString('ru-RU')

/** Список загружен не целиком (потолок `listAllResource`). Отличается от сетевого сбоя тем, что повтор загрузки даст тот же результат. */
export class IncompleteDataError extends Error {
  /** Что загружалось («Установленное ПО») — для разбора ошибки вызывающим кодом. */
  readonly what: string
  /** Сколько записей получено. */
  readonly loaded: number
  /** Сколько записей на сервере. */
  readonly total: number

  constructor(what: string, loaded: number, total: number) {
    super(`Список «${what}» загружен не полностью (${formatCount(loaded)} из ${formatCount(total)}). Сохранение заблокировано, чтобы не стереть данные.`)
    this.name = 'IncompleteDataError'
    this.what = what
    this.loaded = loaded
    this.total = total
  }
}

/**
 * Возвращает ответ `listAllResource` как есть, если он полный, и бросает `IncompleteDataError`, если он усечён.
 *
 * @param what — что загружалось, в именительном падеже, как в заголовке списка: «Установленное ПО», «VLAN устройства».
 *
 * @example
 *   const software = assertComplete(await listAllResource<DeployedSoftware>('deployed-software', { owner_id }), 'Установленное ПО')
 */
export function assertComplete<R extends CompletenessInfo>(res: R, what: string): R {
  if (res.truncated) throw new IncompleteDataError(what, res.items.length, res.total)
  return res
}
