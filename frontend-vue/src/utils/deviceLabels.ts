// Подписи устройства из справочников, общие для таблиц («Инвентаризация устройств», «Стеки устройств»). Пустое значение —
// пустая строка: что показывать вместо него («—», ничего), решает таблица, а не эта функция.
import type { Device } from '../api/types'
import type { useCatalogsStore } from '../stores/catalogs'

/** Часть стора справочников, которая нужна подписям: так функции проверяются на простых заглушках, без Pinia. */
export type DeviceLabelCatalogs = Pick<ReturnType<typeof useCatalogsStore>, 'label' | 'indexOf'>

function catalogName(catalogs: DeviceLabelCatalogs, key: 'buildings' | 'rooms', id: string | null): string {
  if (!id) return ''
  return (catalogs.indexOf(key).get(id)?.name as string | undefined) ?? ''
}

/** «Производитель · модель»; заданное только одно из двух — только оно; ничего не задано — ''. */
export function deviceModelLabel(catalogs: DeviceLabelCatalogs, d: Pick<Device, 'manufacturer_id' | 'model_id'>): string {
  return [catalogs.label('manufacturers', d.manufacturer_id, ''), catalogs.label('device-models', d.model_id, '')].filter(Boolean).join(' · ')
}

/** «Здание · помещение»; название, которого нет в справочнике (удалено, не загружено), пропускается; ничего нет — ''. */
export function devicePlaceLabel(catalogs: DeviceLabelCatalogs, d: Pick<Device, 'building_id' | 'room_id'>): string {
  return [catalogName(catalogs, 'buildings', d.building_id), catalogName(catalogs, 'rooms', d.room_id)].filter(Boolean).join(' · ')
}
