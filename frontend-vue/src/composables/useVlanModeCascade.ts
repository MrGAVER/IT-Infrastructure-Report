// Каскадная смена режима порта (access/trunk) для любого места интерфейса: форма устройства
// («Применить конфигурацию соседа» / «Применить текущую конфигурацию») и дашборд «Подключения».
// Сервер считает область изменения (backend/app/services/vlan_mode_cascade.py), здесь — общий
// сценарий: предпросмотр → (тривиальный план применяется сразу) либо окно подтверждения со всеми
// последствиями → применение → обновление кэша, черновика формы и вызывающего экрана.
//
// Вызывающий экран описывает себя через CascadeHost:
//  * edited() — состояние открытой формы (null, если формы нет — дашборд): сервер не пишет порты и
//    группы этого устройства, а отдаёт их в плане как deferred;
//  * applyDeferred() — внести deferred-часть плана в черновик формы, вернуть число изменённых портов;
//  * onFinished() — каскад завершён (применён или менять нечего): закрыть окно, перечитать список.
import { ref } from 'vue'
import { ApiError } from '../api/client'
import { applyVlanModeCascade, previewVlanModeCascade, type EditedDeviceState, type VlanMode, type VlanModeCascadePlan } from '../api/vlanModeCascade'
import type { CatalogItem } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { isTrivialPlan, modeLabel } from '../utils/vlanModeCascade'
import { useToast } from './useToast'

export interface CascadeHost {
  edited: () => EditedDeviceState | null
  applyDeferred?: (plan: VlanModeCascadePlan) => number
  onFinished?: () => void | Promise<void>
}

/** Что сделал start(): применил сразу, нечего менять или ждёт подтверждения в окне. */
export type CascadeStartOutcome = 'applied' | 'unchanged' | 'confirm'

export interface PendingCascade {
  plan: VlanModeCascadePlan
  /** Порт, с которого начинается смена: сервер от него считает область. */
  interfaceId: string
  /** Подпись этого порта для окна: «b1» (CAS-GB). */
  portLabel: string
  /** Состояние формы на момент предпросмотра: то же уходит и при применении, иначе hash плана не сойдётся. */
  edited: EditedDeviceState | null
}

export function useVlanModeCascade(host: CascadeHost) {
  const catalogs = useCatalogsStore()
  const { notify, notifyError } = useToast()
  const pending = ref<PendingCascade | null>(null)
  const applying = ref(false)

  async function finish(): Promise<void> {
    pending.value = null
    await host.onFinished?.()
  }

  async function commit(current: PendingCascade): Promise<void> {
    const result = await applyVlanModeCascade(current.interfaceId, current.plan, current.edited)
    for (const item of result.interfaces) catalogs.replaceInterface(item as unknown as CatalogItem)
    const formPorts = host.applyDeferred?.(current.plan) ?? 0
    const mode = modeLabel(current.plan.target_mode)
    const inForm = `в этой форме изменено портов: ${formPorts} — сохраните форму`
    let message = `Режим ${mode} уже установлен`
    if (result.applied.ports > 0) message = `Режим ${mode} установлен у портов: ${result.applied.ports}${formPorts > 0 ? `; ${inForm}` : ''}`
    else if (formPorts > 0) message = `Режим ${mode}: ${inForm}`
    notify(message, 'success')
    await finish()
  }

  /** Предпросмотр смены режима порта `interfaceId` на `mode`. null — менять нечего (пользователю уже
   * сообщили, экран завершён). Ошибки (в т.ч. «область слишком большая») пробрасываются вызывающему:
   * у каждого экрана свой способ их показать. */
  async function preview(interfaceId: string, mode: VlanMode, portLabel: string): Promise<PendingCascade | null> {
    const edited = host.edited()
    const plan = await previewVlanModeCascade(interfaceId, mode, edited)
    if (plan.empty) {
      notify('Режим порта уже совпадает', 'info')
      await finish()
      return null
    }
    return { plan, interfaceId, portLabel, edited }
  }

  /** Показывает окно подтверждения для плана из preview(). */
  function review(current: PendingCascade): void {
    pending.value = current
  }

  /** Предпросмотр и дальше: тривиальный план применяется сразу, остальное ждёт подтверждения в окне. */
  async function start(interfaceId: string, mode: VlanMode, portLabel: string): Promise<CascadeStartOutcome> {
    const current = await preview(interfaceId, mode, portLabel)
    if (!current) return 'unchanged'
    if (isTrivialPlan(current.plan)) {
      await commit(current)
      return 'applied'
    }
    review(current)
    return 'confirm'
  }

  /** «Применить» в окне подтверждения. Если данные изменились после предпросмотра (409), окно
   * показывает новый план и просит подтвердить его заново. */
  async function confirm(): Promise<void> {
    const current = pending.value
    if (!current) return
    applying.value = true
    try {
      await commit(current)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) await refreshPlan(current)
      else notifyError(err)
    } finally {
      applying.value = false
    }
  }

  async function refreshPlan(stale: PendingCascade): Promise<void> {
    try {
      const edited = host.edited()
      const fresh = await previewVlanModeCascade(stale.interfaceId, stale.plan.target_mode, edited)
      if (fresh.empty) {
        notify('Расхождение уже устранено — изменять нечего', 'info')
        await finish()
      } else {
        pending.value = { ...stale, plan: fresh, edited }
        notify('Данные изменились после предпросмотра — план обновлён, проверьте его ещё раз', 'warning')
      }
    } catch (err) {
      notifyError(err)
    }
  }

  function cancel(): void {
    pending.value = null
  }

  return { pending, applying, preview, review, start, confirm, cancel, finish }
}
