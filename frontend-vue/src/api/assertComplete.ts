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

/**
 * Загружает список целиком (`load` — обычно `() => listAllResource(...)`) и бросает `IncompleteDataError`, только если он не набрался и со второй
 * попытки. Усечённый ответ перечитывается ОДИН раз, прежде чем стать ошибкой.
 *
 * Зачем повтор (ИБ-05, ревью merge/review-r3-executors): `truncated` считается как «получено меньше, чем `total` с первой страницы». Если пока
 * читались страницы, чью-то запись удалили, `total` устарел, и признак ложно срабатывает, хотя список как раз целый: форма отказывалась
 * сохраняться, пока пользователь сам не закроет и не откроет её заново. Повторная загрузка берёт свежий `total` и в таком случае проходит.
 *
 * Повторяется только усечение. Ошибка самой загрузки (сеть, 4xx/5xx) пробрасывается сразу: повтор запроса — дело вызывающего кода.
 * Если список упёрся в настоящий потолок `listAllResource` (50 000 записей), повтор даст то же самое и обойдётся ещё одной полной загрузкой, но
 * это редкий случай, и до ошибки он доходит так же, как раньше.
 *
 * @param load — загрузка списка; вызывается заново при повторе, поэтому не должна иметь побочных эффектов
 * @param what — что загружалось, в именительном падеже (как у `assertComplete`)
 *
 * @example
 *   const software = await loadAllComplete(() => listAllResource<DeployedSoftware>('deployed-software', { owner_id }), 'Установленное ПО')
 */
export async function loadAllComplete<R extends CompletenessInfo>(load: () => Promise<R>, what: string): Promise<R> {
  const first = await load()
  if (!first.truncated) return first
  return assertComplete(await load(), what)
}
