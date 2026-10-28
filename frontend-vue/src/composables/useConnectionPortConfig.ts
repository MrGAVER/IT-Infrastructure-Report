// Сверка конфигурации выбранной пары портов в форме подключения (ConnectionFormModal.vue).
//
// Сверку делает СЕРВЕР — GET /connections/port-config/preview: те же правила и то же одобрение, что у дашборда «Подключения»
// (services/port_config.py), поэтому предупреждение формы и статус после сохранения не могут разойтись, а клиент не дублирует
// правила (VLAN портов в каталоге интерфейсов нет вовсе). Расхождение — когда различается роль, режим порта или набор VLAN;
// неактивное подключение расхождением не считается. До ответа сервера (или если запрос не удался) форма сверяет хотя бы роли по
// каталогу (utils/connectionPortView.ts: buildConfigView).
import { computed, ref, watch } from 'vue'
import { previewPortConfig } from '../api/portConfig'
import type { DeviceInterface, PortConfigPreview } from '../api/types'
import { buildConfigView } from '../utils/connectionPortView'
import { portRoleOf } from '../utils/portConfig'

export interface ConnectionPortConfigDeps {
  source: () => DeviceInterface | null
  destination: () => DeviceInterface | null
  /** id редактируемого подключения (у нового — undefined): сервер учитывает его одобрение. */
  connectionId: () => string | undefined
  isActive: () => boolean
}

export function useConnectionPortConfig(deps: ConnectionPortConfigDeps) {
  const preview = ref<PortConfigPreview | null>(null)
  let seq = 0
  // Последний запущенный запрос сверки: submit() дожидается его (settle), чтобы решение принималось по свежим данным, даже если
  // пользователь нажал «Сохранить» сразу после выбора порта.
  let pending: Promise<void> = Promise.resolve()

  async function load(): Promise<void> {
    const s = deps.source()
    const d = deps.destination()
    const current = ++seq
    if (!s || !d) {
      preview.value = null
      return
    }
    try {
      const result = await previewPortConfig({
        source_interface_id: s.id,
        destination_interface_id: d.id,
        connection_id: deps.connectionId(),
        is_active: deps.isActive(),
      })
      // Ответ без обеих сторон (не тот сервер, прокси) приравнивается к неудаче — сработает сверка ролей по каталогу.
      if (current === seq) preview.value = result?.source && result?.destination ? result : null
    } catch {
      if (current === seq) preview.value = null
    }
  }

  /** Перезапрашивает сверку; промис завершается, когда ответ учтён (или запрос не удался). */
  function refresh(): Promise<void> {
    pending = load()
    return pending
  }

  /** Дожидается последнего запущенного запроса сверки. */
  function settle(): Promise<void> {
    return pending
  }

  const configView = computed(() => buildConfigView(deps.source(), deps.destination(), preview.value))
  const portMismatch = computed(() => (configView.value && configView.value.status !== 'ok' ? configView.value : null))
  // При правке подключения, расхождение которого уже одобрено и не изменилось, повторно спрашивать не нужно — сервер сверяет
  // одобрение по ровно этому расхождению (approval_signature).
  const mismatchAlreadyApproved = computed(() => configView.value?.status === 'approved')
  /** Расхождение, по которому нужно решение пользователя (нет расхождения или оно уже одобрено — false). */
  const needsResolution = computed(() => !!portMismatch.value && !mismatchAlreadyApproved.value)

  // Пересчёт сверки при смене пары портов, активности, роли или режима любого из них (в том числе после «Управлять портами» и
  // выравнивания роли). Ключ — только то, от чего зависит ответ.
  const previewKey = computed(() => {
    const s = deps.source()
    const d = deps.destination()
    if (!s || !d) return null
    const config = (i: DeviceInterface) => `${portRoleOf(i)}/${i.vlan_mode}`
    return [s.id, d.id, deps.isActive(), deps.connectionId() ?? '', config(s), config(d)].join('|')
  })
  watch(
    previewKey,
    () => {
      void refresh()
    },
    { immediate: true },
  )

  return { preview, configView, portMismatch, mismatchAlreadyApproved, needsResolution, refresh, settle }
}

export type ConnectionPortConfig = ReturnType<typeof useConnectionPortConfig>
