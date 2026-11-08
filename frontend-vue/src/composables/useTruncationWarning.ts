// R2-01 (ревью merge/review-f06-stage2-f05-executors): listAllResource больше не обрезает выборку молча — при `truncated === true`
// экран, которому нужна полнота, обязан сказать об этом пользователю. Единая формулировка живёт здесь, чтобы не расходиться по экранам.
import type { AllPagesResponse } from '../api/client'
import { useToast } from './useToast'

type TruncatableResponse = Pick<AllPagesResponse<unknown>, 'items' | 'total' | 'truncated'>

/**
 * Показывает предупреждение «Показана часть данных», если полная загрузка ресурса усечена. Возвращает `res.truncated`,
 * чтобы вызывающий код мог при необходимости ещё и заблокировать действие, опирающееся на полноту (например, массовое удаление).
 *
 * @param what — что именно загружалось, в родительном падеже после «данных»: «подключений», «IP-адресов ВМ».
 *
 * @example
 *   const res = await listAllResource<Connection>('connections')
 *   warnIfTruncated(res, 'подключений')
 */
export function warnIfTruncated(res: TruncatableResponse, what: string): boolean {
  if (res.truncated !== true) return false
  const format = (n: number) => n.toLocaleString('ru-RU')
  useToast().notify(
    `Показана часть данных (${what}): загружено ${format(res.items.length)} из ${format(res.total)}. Остальные записи не отображаются.`,
    'warning',
  )
  return true
}
