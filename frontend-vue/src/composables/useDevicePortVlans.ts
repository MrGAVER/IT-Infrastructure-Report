// VLAN портов в форме устройства (DeviceFormModal.vue): какие VLAN можно поставить на порт и что происходит с портами и
// группами, когда набор допустимых VLAN меняется.
import { computed, watch } from 'vue'
import { computePortVlanOptions } from '../api/portVlans'
import { useVLANsStore } from '../stores/vlans'
import { groupVlanRemovalMessage, reconcileVlanIds } from '../utils/vlan'
import { subinterfaceVlanRemovalMessage } from '../utils/subinterfaces'
import { useToast } from './useToast'
import type { DeviceDraft } from './useDeviceDraft'

export interface DevicePortVlansDeps {
  /** Показать в редакторе портов подинтерфейсы на снятом VLAN (кнопка «Показать» в предупреждении). */
  revealStaleSubinterfaces: () => void
}

export function useDevicePortVlans(draft: DeviceDraft, deps: DevicePortVlansDeps) {
  const vlansStore = useVLANsStore()
  const { notify } = useToast()

  // Опции для чекбоксов "VLAN на порту" (DeviceInterfacesEditor.vue) — НЕ то же самое, что
  // availableVlans (useDeviceDomains.ts): тот отвечает "что можно НАЗНАЧИТЬ устройству" (фильтр по домену), этот —
  // "что уже разрешено/назначено устройству, поэтому можно поставить на порт" (тип устройства ∪
  // текущий черновик deviceVlans, ещё не обязательно сохранённый — так пользователь может
  // одновременно добавить VLAN устройству и в этом же сохранении назначить его порту). См.
  // api/portVlans.ts.
  const portVlanOptions = computed(() =>
    computePortVlanOptions(vlansStore.allDefinitions, draft.deviceTypeVlanIds.value, new Set(draft.deviceVlans.value.map((r) => r.vlan_id).filter(Boolean))),
  )

  // Если VLAN устройства перестал быть опцией порта (пользователь снял его в блоке "VLAN
  // устройства" или сменил тип устройства), убираем его и из vlan_ids уже заведённых портов —
  // иначе сохранение упадёт 422 "VLAN не разрешён для типа данного устройства", а пользователь не
  // поймёт, откуда ошибка. То же поведение, что syncDeviceVlanOptionsFromRows() в vanilla-версии.
  //
  // «Все VLAN» (порт или группа с признаком all_vlans, trunk) — сохраняемый признак: его vlan_ids зеркалит ВСЕ
  // допустимые VLAN устройства, поэтому при добавлении нового VLAN в блоке "VLAN устройства" порт подхватывает
  // его сам, а при снятии — теряет. Вручную выбранный полный набор признаком не является и новых VLAN не получает
  // (раньше «все» выводилось из набора — это и ломалось: признак нельзя было ни сохранить, ни отличить от выбора).
  //
  // КРИТИЧНО: сравниваем НОВЫЙ список опций со СТАРЫМ (аргумент oldOptions от Vue) и трогаем
  // только vlan_ids, которые были разрешены раньше и перестали быть разрешены сейчас — а не
  // просто "не входят в текущий portVlanOptions". Первое срабатывание случится сразу после
  // начальной загрузки устройства (oldOptions на этот момент — пустой массив от самого первого
  // вычисления computed, ещё до загрузки), и разница будет пустой — начальная загрузка порт не
  // тронет. Если бы вместо диффа проверялось только текущее значение, при первой же загрузке
  // стёрлись бы vlan_ids, назначенные через /legacy, но не входящие в этот более узкий каталог
  // (тип устройства ∪ уже назначенные) — ровно такой баг поймал регрессионный тест в
  // DeviceFormModal.spec.ts ("не стирает VLAN интерфейса, назначенные через /legacy...").
  //
  // Те же правила применяются и к ГРУППАМ портов (interfaceGroups): группа хранит свой vlan_ids, и
  // сервер при сохранении записывает его во все порты группы — не обновлённая группа затёрла бы
  // только что подхваченный портом новый VLAN (и оставила бы в группе снятый). Сама логика — в чистой
  // функции reconcileVlanIds (utils/vlan.ts), общая для портов и групп.
  watch(portVlanOptions, (options, oldOptions) => {
    const previous = oldOptions ?? []
    const rows = draft.interfaces.value
    const nextRows = rows.map((row) => {
      const vlan_ids = reconcileVlanIds(row.vlan_ids, row.vlan_mode, row.all_vlans === true, previous, options)
      return vlan_ids === row.vlan_ids ? row : { ...row, vlan_ids }
    })
    if (nextRows.some((row, i) => row !== rows[i])) draft.interfaces.value = nextRows

    // Подинтерфейсы, в отличие от VLAN порта и групп, молча не удаляются (на них IP-адреса и открытые порты): остаются на
    // снятом VLAN, подсвечиваются в редакторе портов и блокируют сохранение. Предупреждаем сразу, а не 422 при сохранении.
    const subinterfaceNotice = subinterfaceVlanRemovalMessage(nextRows, previous, options)
    if (subinterfaceNotice) {
      notify(subinterfaceNotice, 'warning', { action: { label: 'Показать', run: () => deps.revealStaleSubinterfaces() } })
    }

    const groups = draft.interfaceGroups.value
    const nextGroups = groups.map((group) => {
      const vlan_ids = reconcileVlanIds(group.vlan_ids, group.vlan_mode, group.all_vlans === true, previous, options)
      return vlan_ids === group.vlan_ids ? group : { ...group, vlan_ids }
    })
    if (nextGroups.some((group, i) => group !== groups[i])) {
      draft.interfaceGroups.value = nextGroups
      // Из групп VLAN убираются молча — предупреждаем: набор VLAN группы изменился не по действию пользователя в самой группе.
      const removalNotice = groupVlanRemovalMessage(groups, nextGroups, previous)
      if (removalNotice) notify(removalNotice, 'warning')
    }
  })

  return { portVlanOptions }
}
