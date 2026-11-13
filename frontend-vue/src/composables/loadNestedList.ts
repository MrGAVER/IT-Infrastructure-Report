// Формы, которые сохраняют вложенный список ЦЕЛИКОМ (IP-адреса, открытые порты и ПО ВМ — PUT /vms/{id}/…, порты, ПО и VLAN устройства),
// опираются на то, что в черновике лежит ровно то, что сейчас в БД: сервер приводит список к присланному, то есть удаляет записи,
// которых в запросе нет. Поэтому «не загрузился» и «загружен не целиком» нельзя путать с «пуст»: сохранение пустого или усечённого
// списка стёрло бы живые данные. Этот модуль превращает результат загрузки в явное состояние, по которому форма решает, показывать ли
// редактор и отправлять ли список.
import type { AllPagesResponse } from '../api/client'
import { warnIfTruncated } from './useTruncationWarning'

/** Почему список нельзя сохранять: не загрузился совсем (`failed`) или загружен не целиком (`partial`, потолок listAllResource). */
export type NestedLoadIssue = { kind: 'failed' } | { kind: 'partial'; loaded: number; total: number }

export interface NestedListResult<T> {
  /** Строки списка. Пусто, если `issue` задан: неполные данные форме не отдаются, чтобы их не показали и не сохранили. */
  items: T[]
  /** `null` — список получен целиком, его можно показывать и сохранять. */
  issue: NestedLoadIssue | null
  /** Исходная ошибка при `issue.kind === 'failed'` — чтобы форма показала её текст. */
  error?: unknown
}

/**
 * Загружает один вложенный список и отвечает на вопрос «можно ли его сохранять». Ошибка не пробрасывается и не глотается: она
 * возвращается в `error`, а список помечается `failed`. Усечённая выборка (`truncated`) помечается `partial` и, как и раньше,
 * сопровождается предупреждением `warnIfTruncated`.
 *
 * @param what — что загружается, в родительном падеже («IP-адресов ВМ»): попадает в предупреждение об усечении.
 *
 * @example
 *   const ips = await loadNestedList(() => listAllResource<IPAddress>('ip-addresses', owner), 'IP-адресов ВМ')
 *   if (!ips.issue) rows.value = ips.items.map(toRow)
 */
export async function loadNestedList<T>(load: () => Promise<AllPagesResponse<T>>, what: string): Promise<NestedListResult<T>> {
  let res: AllPagesResponse<T>
  try {
    res = await load()
  } catch (error) {
    return { items: [], issue: { kind: 'failed' }, error }
  }
  if (warnIfTruncated(res, what)) return { items: [], issue: { kind: 'partial', loaded: res.items.length, total: res.total } }
  return { items: res.items, issue: null }
}
