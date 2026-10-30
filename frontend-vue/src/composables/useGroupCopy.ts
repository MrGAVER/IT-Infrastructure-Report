// Копирование значений с порта в черновик группы (блок «Скопировать значения с порта» окна группы, GroupCopyBlock.vue).
//
// Порт-источник выбирается среди портов этого устройства (строки редактора). Копируются только отмеченные параметры, у
// которых на порту есть значение (utils/interfaceGroups.ts:copyableFields); копия попадает в черновик группы и
// применяется к портам, как и любое другое значение, при сохранении группы.
import { computed, ref, watch } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { copyValuesFromRow, copyableFields, subinterfaceTemplatesFromRow, type ManagedFields } from '../utils/interfaceGroups'
import { useToast } from './useToast'

export interface GroupCopyDeps {
  rows: () => InterfaceDraftRow[]
  vlanOptions: () => VLANDefinition[]
  protocolPortCatalog: () => ProtocolPortCatalogEntry[]
  /** Текущий черновик группы, в который копируются значения. */
  draft: () => InterfaceGroupDraft
  /** Принять новый черновик (старый не мутируется). */
  apply: (group: InterfaceGroupDraft) => void
}

const none = (): ManagedFields => ({ vlan: false, ip: false, openPorts: false, subinterfaces: false })

export function useGroupCopy(deps: GroupCopyDeps) {
  const { notify } = useToast()

  const copySource = ref('')
  const copyWhat = ref<ManagedFields>(none())

  const copyPortOptions = computed(() => deps.rows().map((row, i) => ({ value: String(i), label: row.name || `#${i + 1}` })))
  const copyRow = computed(() => (copySource.value === '' ? undefined : deps.rows()[Number(copySource.value)]))
  const copyAvailable = computed(() => (copyRow.value ? copyableFields(copyRow.value) : none()))
  const copyNothingAvailable = computed(
    () => !!copyRow.value && !copyAvailable.value.vlan && !copyAvailable.value.ip && !copyAvailable.value.openPorts && !copyAvailable.value.subinterfaces,
  )
  const canCopy = computed(
    () =>
      (copyWhat.value.vlan && copyAvailable.value.vlan) ||
      (copyWhat.value.ip && copyAvailable.value.ip) ||
      (copyWhat.value.openPorts && copyAvailable.value.openPorts) ||
      (copyWhat.value.subinterfaces && copyAvailable.value.subinterfaces),
  )

  function resetCopy() {
    copySource.value = ''
    copyWhat.value = none()
  }

  // Выбрали порт — сразу отмечаем всё, что с него можно скопировать.
  watch(copySource, () => {
    copyWhat.value = { ...copyAvailable.value }
  })

  function copyFromPort() {
    const row = copyRow.value
    if (!row || !canCopy.value) return
    const deviceVlanIds = new Set(deps.vlanOptions().map((v) => v.id))
    const next = copyValuesFromRow(deps.draft(), row, copyWhat.value, deps.protocolPortCatalog(), deviceVlanIds)
    deps.apply(next)
    const label = row.name || `#${Number(copySource.value) + 1}`
    notify(`Значения скопированы с порта «${label}».`, 'success')
    // Подинтерфейсы на VLAN, которых нет в VLAN группы, шаблонами не становятся: говорим об этом, а не теряем молча.
    if (copyWhat.value.subinterfaces && copyAvailable.value.subinterfaces) {
      const { templates, skipped } = subinterfaceTemplatesFromRow(row, next, deviceVlanIds)
      if (skipped.length) {
        const names = skipped.map((sub) => `«${sub.name.trim() || 'без имени'}»`).join(', ')
        notify(
          templates.length
            ? `Не скопированы подинтерфейсы на VLAN, которых нет в VLAN группы: ${names}.`
            : `Подинтерфейсы не скопированы: их VLAN нет в VLAN группы (${names}). Задайте режим порта и VLAN группы — или скопируйте их вместе с режимом порта и VLAN.`,
          'warning',
        )
      }
    }
    resetCopy()
  }

  return { copySource, copyWhat, copyPortOptions, copyRow, copyAvailable, copyNothingAvailable, canCopy, copyFromPort }
}
