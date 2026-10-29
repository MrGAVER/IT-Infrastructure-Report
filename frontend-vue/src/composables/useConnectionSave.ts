// Сохранение подключения (ConnectionFormModal.vue) и решение по расхождению конфигурации портов.
//
// «Назначение линии связи» (управление / передача данных) в подключении не хранится и не вводится: оно целиком определяется ролями
// двух портов (DeviceInterface.is_management / is_data_transfer). Если конфигурация портов (роль, режим trunk/access, VLAN)
// различается, форма НЕ даёт сохранить подключение, пока пользователь явно не выберет решение: выровнять роль одного из портов,
// выровнять режим порта (каскадом — composables/useVlanModeCascade.ts: режим могут задавать группы портов, и он должен совпасть у
// связанных портов; перед применением показываются все последствия), поправить VLAN в окне портов («Управлять портами») или одобрить
// расхождение как допустимое. Так проверка срабатывает каждый раз, а не только когда предупреждение заметили.
import type { Ref } from 'vue'
import { createResource, updateResource } from '../api/client'
import { approvePortConfig, setPortRole } from '../api/portConfig'
import type { Connection } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { connectionPayload, validateConnectionForm } from '../utils/connectionForm'
import type { MismatchResolution } from '../utils/connectionPortView'
import { useToast } from './useToast'
import { useVlanModeCascade } from './useVlanModeCascade'
import type { ConnectionDraft } from './useConnectionDraft'
import type { ConnectionPortConfig } from './useConnectionPortConfig'

export interface ConnectionSaveDeps {
  /** Редактируемое подключение (null — создание). */
  connection: () => Connection | null
  /** Роль без права записи (viewer): сохранять нечего. */
  readOnly: Ref<boolean>
  onSaved: (connection: Connection) => void
}

export function useConnectionSave(draft: ConnectionDraft, portConfig: ConnectionPortConfig, deps: ConnectionSaveDeps) {
  const catalogs = useCatalogsStore()
  const { notify } = useToast()
  const { form, errorMessage, saving, resolving } = draft

  async function submit() {
    if (deps.readOnly.value) return
    errorMessage.value = null
    const invalid = validateConnectionForm(form)
    if (invalid) {
      errorMessage.value = invalid
      return
    }
    await portConfig.settle() // сверка могла ещё не вернуться
    // Расхождение нельзя сохранить «молча»: сначала пользователь выбирает решение.
    if (portConfig.needsResolution.value) {
      resolving.value = true
      return
    }
    await persist(null)
  }

  /** Расхождение осталось (например, после выравнивания роли режим или VLAN всё ещё различаются): молча сохранять нельзя —
   * спрашиваем про остаток, иначе подключение сохраняется. */
  async function resolveRemainderOrPersist() {
    if (portConfig.needsResolution.value) {
      resolving.value = true
      return
    }
    await persist(null)
  }

  async function resolveAndSave(resolution: MismatchResolution) {
    if (deps.readOnly.value) return // шаг достижим только из submit(), но запись не должна уйти ни при каких обстоятельствах
    resolving.value = false
    if (resolution === 'approve') {
      await persist('approve')
      return
    }
    if (resolution === 'mode-keep-source' || resolution === 'mode-keep-destination') {
      await alignMode(resolution === 'mode-keep-source')
      return
    }
    saving.value = true
    try {
      await alignPort(resolution === 'keep-source')
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось изменить роль порта'
      return
    } finally {
      saving.value = false
    }
    await portConfig.refresh()
    await resolveRemainderOrPersist()
  }

  /** Приводит роль одного порта к роли второго. Порт меняется отдельным точечным запросом (не синхронизацией устройства целиком)
   * и сразу до сохранения подключения: если сохранение потом не удастся, выбранная пользователем роль порта остаётся, а повторная
   * отправка формы уже не увидит расхождения. */
  async function alignPort(keepSource: boolean) {
    const mismatch = portConfig.portMismatch.value
    if (!mismatch) return
    const winner = keepSource ? mismatch.source : mismatch.destination
    const loser = keepSource ? mismatch.destination : mismatch.source
    catalogs.replaceInterface(await setPortRole(loser.id, winner.role))
  }

  // Формы устройства здесь нет (edited = null): изменения всех портов записываются сразу. Режим выровнен (или уже совпадал) — как
  // после выравнивания роли: сверка пересчитывается, остаток (VLAN) снова требует решения, иначе подключение сохраняется.
  const cascade = useVlanModeCascade({
    edited: () => null,
    async onFinished() {
      await portConfig.refresh()
      await resolveRemainderOrPersist()
    },
  })

  /** Приводит режим одного порта к режиму второго — каскадом: режим могут задавать группы портов, и он должен совпасть у связанных
   * портов, поэтому сервер считает всю область изменения, а при необходимости окно показывает последствия до применения. Как и
   * роль, режим записывается сразу, до сохранения подключения. Продолжение (пересчёт сверки и сохранение) — в onFinished каскада. */
  async function alignMode(keepSource: boolean) {
    const mismatch = portConfig.portMismatch.value
    if (!mismatch) return
    const winner = keepSource ? mismatch.source : mismatch.destination
    const loser = keepSource ? mismatch.destination : mismatch.source
    if (!winner.mode) return
    saving.value = true
    try {
      await cascade.start(loser.id, winner.mode, `«${loser.name}» (${draft.endpointDeviceLabel(keepSource ? 'destination' : 'source')})`)
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось изменить режим порта'
    } finally {
      saving.value = false
    }
  }

  /** «Отмена» в окне последствий: ничего не записано — возвращаемся к выбору решения. */
  function cancelCascade() {
    cascade.cancel()
    resolving.value = true
  }

  async function persist(resolution: 'approve' | null) {
    saving.value = true
    try {
      const payload = connectionPayload(form)
      const existing = deps.connection()
      const saved = existing ? await updateResource<Connection>('connections', existing.id, payload) : await createResource<Connection>('connections', payload)
      if (resolution === 'approve') {
        try {
          await approvePortConfig([saved.id])
        } catch (err) {
          // Подключение уже сохранено — форму закрываем как обычно, а о неудаче одобрения говорим отдельно: расхождение останется в
          // списке «Расхождения» дашборда.
          notify(`Подключение сохранено, но расхождение не одобрено: ${err instanceof Error ? err.message : 'ошибка'}`, 'warning')
        }
      }
      deps.onSaved(saved)
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить подключение'
    } finally {
      saving.value = false
    }
  }

  return {
    submit,
    resolveAndSave,
    cancelCascade,
    cascadePending: cascade.pending,
    cascadeApplying: cascade.applying,
    cascadeConfirm: cascade.confirm,
  }
}
