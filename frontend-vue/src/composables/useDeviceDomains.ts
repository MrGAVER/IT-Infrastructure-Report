// Домены VLAN в форме устройства (DeviceFormModal.vue): какие VLAN можно назначить устройству, в какие домены оно уже входит
// или будет включено при сохранении, и запись этого на сервер.
import { computed } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { CatalogItem, DeviceMemberDomain } from '../api/types'
import { useVLANDomainsStore } from '../stores/vlanDomains'
import { useVLANsStore } from '../stores/vlans'
import { sortDeviceVlanRows } from '../utils/deviceVlans'
import { filterVlansForDeviceDomains, mergeDomainVlansIntoDraft, removeDomainVlansFromDraft } from '../utils/vlan'
import type { DeviceDraft } from './useDeviceDraft'

export function useDeviceDomains(draft: DeviceDraft) {
  const vlansStore = useVLANsStore()
  const vlanDomainsStore = useVLANDomainsStore()

  // Домены VLAN, в которых устройство состоит: сохранённое членство (memberDomainIds) плюс домены,
  // добавленные в этой же сессии редактирования и ещё не сохранённые (pendingDomainMemberships,
  // фикс п.1.3.8 — устройство уже "фактически" их участник для целей этой формы).
  const deviceDomainIds = computed(() => new Set([...draft.memberDomainIds.value, ...draft.pendingDomainMemberships.value]))

  // Правка "VLAN устройства" (пункт 3): если устройство состоит в домене VLAN, в списке выбора
  // показываются ТОЛЬКО VLAN этого домена (доменов — если их несколько); если не состоит ни в одном —
  // только VLAN без домена (доменные для не-участника бэкенд всё равно отклонил бы 422). Само правило
  // вынесено в utils/vlan.ts:filterVlansForDeviceDomains — чистая функция, покрыта отдельными тестами.
  const availableVlans = computed(() => filterVlansForDeviceDomains(vlansStore.allDefinitions, deviceDomainIds.value))

  // Фикс п.2.2: единственный домен, к которому уже привязано устройство — только если он ровно
  // один (см. комментарий к deviceDomainId в DeviceVlanListEditor.vue). Учитывает и
  // pendingDomainMemberships через deviceDomainIds выше.
  const singleDeviceDomainId = computed(() => (deviceDomainIds.value.size === 1 ? [...deviceDomainIds.value][0] : null))

  // Пункт 3 правки "домен VLAN": кнопка "Включить в домен" в блоке "VLAN устройства"
  // (DeviceVlanListEditor.vue) — прямой путь стать участником УЖЕ СУЩЕСТВУЮЩЕГО домена, в отличие
  // от косвенного onVlanDomainCreated ниже (который срабатывает только как побочный эффект
  // заведения нового VLAN). Тот же pendingDomainMemberships и та же проверка "ещё не состоит".
  const joinableDomains = computed(() => vlanDomainsStore.all.filter((d) => !draft.memberDomainIds.value.has(d.id) && !draft.pendingDomainMemberships.value.has(d.id)))

  // Пункты 3-4 правки "включение в домен VLAN": домены, в которых устройство состоит (или будет
  // состоять после сохранения) — показываются в блоке "VLAN устройства", чтобы включение было видно
  // сразу, а не только после перезагрузки страницы. Домены, которых ещё нет в vlanDomainsStore (например,
  // только что созданный вложенным "+"), пропускаются — onVlanDomainCreated перезагружает стор, и они
  // появятся сразу после его ответа.
  const memberDomains = computed<DeviceMemberDomain[]>(() => {
    const nameById = new Map(vlanDomainsStore.all.map((d) => [d.id, d.name]))
    const result: DeviceMemberDomain[] = []
    for (const id of draft.memberDomainIds.value) {
      if (nameById.has(id)) result.push({ id, name: nameById.get(id)!, pending: false })
    }
    for (const id of draft.pendingDomainMemberships.value) {
      if (!draft.memberDomainIds.value.has(id) && nameById.has(id)) result.push({ id, name: nameById.get(id)!, pending: true })
    }
    return result
  })

  // Фикс п.1.3.8: домены VLAN на форме устройства — read-only список (галочки участников редактируются только в
  // VLANDomainsPanel.vue), но нет способа стать участником домена, который только что создан ЗДЕСЬ ЖЕ, вложенным быстрым
  // добавлением при заведении VLAN (domain_id -> nestedQuickAdd в quickAdd/schema.ts) — созданный VLAN принадлежит домену, в
  // котором устройство не состоит, и availableVlans его тут же отфильтровал бы. domain_id может отсутствовать (VLAN без
  // домена — общедоступен всем устройствам) или уже быть в числе подтверждённых участников (самый частый случай) — тут
  // добавлять нечего, только оверхед на бэкенде при сохранении.
  function onVlanCreated(record: CatalogItem) {
    vlansStore.reload()
    const domainId = (record as { domain_id?: string | null }).domain_id
    if (domainId && !draft.memberDomainIds.value.has(domainId)) {
      draft.pendingDomainMemberships.value = new Set([...draft.pendingDomainMemberships.value, domainId])
    }
  }

  // Пункт 3 правки "создание физического устройства": в отличие от onVlanCreated выше (который реагирует на выбор ЛЮБОГО
  // домена, включая уже существующий), это — событие именно СОЗДАНИЯ нового домена вложенным "+" (цепочка nested-created в
  // QuickAddModal.vue/QuickAddButton.vue/DeviceVlanListEditor.vue). Домен почти наверняка создан РАДИ синхронизации именно
  // этого устройства, а не выбран из списка существующих (тот трогать нельзя — у него уже могут быть свои
  // источник/участники/настройки). Само присвоение source_device_id/auto_sync откладывается до persistPendingSourceDomains —
  // у создаваемого устройства ещё может не быть id.
  function onVlanDomainCreated(record: CatalogItem) {
    draft.pendingSourceDomainIds.value = new Set([...draft.pendingSourceDomainIds.value, record.id])
    // Новый домен ещё не в vlanDomainsStore — без перезагрузки его не было бы в списке memberDomains.
    vlanDomainsStore.reload()
  }

  async function onJoinDomainRequested(domainId: string) {
    if (draft.memberDomainIds.value.has(domainId) || draft.pendingDomainMemberships.value.has(domainId)) return
    draft.pendingDomainMemberships.value = new Set([...draft.pendingDomainMemberships.value, domainId])
    // Пункт 4: VLAN выбранного домена сразу попадают в черновик "VLAN устройства". Это не только
    // удобство: persistDeviceVlans() (PUT /devices/{id}/vlans) приводит VLAN устройства в БД ровно к
    // черновику — записи, которых в нём нет, удаляются. Поэтому VLAN, которые бэкенд сам назначит при
    // создании членства (services/crud/vlan_domains.py:assign_domain_vlans_to_device), но которых нет в черновике,
    // были бы тут же убраны при этом же сохранении. Стор перезагружается (а не ensureLoaded), чтобы набор
    // VLAN домена был актуален на момент нажатия, а не на момент первой загрузки экрана.
    await vlansStore.reload()
    // Добавленные VLAN домена встают в общий список по номеру — как при добавлении строки вручную.
    const merged = mergeDomainVlansIntoDraft(draft.deviceVlans.value, vlansStore.allDefinitions, domainId)
    draft.deviceVlans.value = merged === draft.deviceVlans.value ? merged : sortDeviceVlanRows(merged, vlansStore.allDefinitions)
  }

  // Отмена ещё не сохранённого включения в домен (кнопка × на pending-чипе в DeviceVlanListEditor):
  // возвращает форму в состояние до «Включить» — домен снова предлагается в списке, а строки VLAN этого
  // домена (и добавленные автоматически, и выбранные вручную после этого) убираются из черновика, иначе
  // бэкенд отклонил бы их 422 (нет членства). Из pendingSourceDomainIds домен тоже исключается: если бы
  // он остался, устройство всё равно стало бы источником домена (persistPendingSourceDomains), в который
  // пользователь его включать передумал. Уже сохранённое членство (memberDomainIds) отменить нельзя.
  function onCancelJoinDomain(domainId: string) {
    if (!draft.pendingDomainMemberships.value.has(domainId)) return
    draft.pendingDomainMemberships.value = new Set([...draft.pendingDomainMemberships.value].filter((id) => id !== domainId))
    draft.pendingSourceDomainIds.value = new Set([...draft.pendingSourceDomainIds.value].filter((id) => id !== domainId))
    draft.deviceVlans.value = removeDomainVlansFromDraft(draft.deviceVlans.value, vlansStore.allDefinitions, domainId)
  }

  // Фикс п.1.3.8: закрепляет на бэкенде членство устройства в доменах, добавленных локально (см. onVlanCreated и
  // pendingDomainMemberships). ДО persistDeviceVlans — _validate_physical_device_vlan в backend/app/services/crud/validators.py
  // проверяет членство устройства в домене VLAN при сохранении device-vlans и отклоняет запись с 422 "Устройство не включено
  // в домен этого VLAN", если членства ещё нет. Уже созданные связи (joinedDomainIds) при повторе после сбоя пропускаются:
  // POST — не идемпотентен.
  async function persistPendingDomainMemberships(deviceId: string) {
    for (const domainId of draft.pendingDomainMemberships.value) {
      if (draft.joinedDomainIds.has(domainId)) continue
      await createResource('vlan-domain-devices', { physical_device_id: deviceId, domain_id: domainId })
      draft.joinedDomainIds.add(domainId)
    }
  }

  // Пункт 3 правки "создание физического устройства": PUT (не POST) — домен уже существует (создан вложенным quick-add'ом,
  // см. onVlanDomainCreated), здесь только доопределяем source_device_id/auto_sync частичным обновлением. Порядок относительно
  // persistPendingDomainMemberships не важен — оба независимо пишут в vlan-domains разные записи/поля.
  async function persistPendingSourceDomains(deviceId: string) {
    for (const domainId of draft.pendingSourceDomainIds.value) {
      await updateResource('vlan-domains', domainId, { source_device_id: deviceId, auto_sync: true })
    }
  }

  return {
    availableVlans,
    singleDeviceDomainId,
    joinableDomains,
    memberDomains,
    onVlanCreated,
    onVlanDomainCreated,
    onJoinDomainRequested,
    onCancelJoinDomain,
    persistPendingDomainMemberships,
    persistPendingSourceDomains,
  }
}

export type DeviceDomains = ReturnType<typeof useDeviceDomains>
