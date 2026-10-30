// Модель формы устройства (DeviceFormModal.vue): пустая форма, заполнение из устройства-источника, тело запроса, строки
// черновиков и опции поля «Тип / производитель / модель». Чистые функции без Vue и без обращений к API.
import type { Device, DeviceModel, DeployedSoftware, DeviceVLAN, DeviceVlanDraftRow, InterfaceDraftRow, SoftwareAssetDraftRow } from '../api/types'
import { stripIds } from './copyEntity'
import { stripSubinterfaceIds } from './subinterfaces'

export function emptyDeviceForm() {
  return {
    device_type_id: '',
    manufacturer_id: '',
    model_id: '',
    serial_number: '',
    system_name: '',
    operating_system_id: '',
    embedded_os_id: '',
    siem_enabled: false,
    building_id: '',
    room_id: '',
    rack_id: '',
    rack_position: '',
    description: '',
    // Необязательный блок "Сертификат ОАЦ" (models.PhysicalDevice) — заполняется, если на
    // устройстве установлено сертифицированное средство криптографической защиты (см. также
    // CryptoProtectionMeans.physical_device_id, привязываемый со стороны справочника СКЗИ в
    // "Другие справочники"). Оба поля независимы: пара "заполнено/не заполнено" не проверяется.
    oac_certificate_number: '',
    oac_certificate_registry_date: '',
    // Раздел 4.3 ТЗ: ручное переопределение автогенерируемой иконки диаграммы для КОНКРЕТНОГО
    // устройства (побеждает переопределение на уровне DeviceModel, если оно тоже задано).
    diagram_icon_id: '',
  }
}

export type DeviceForm = ReturnType<typeof emptyDeviceForm>

/**
 * Значения формы из устройства: редактируемого (props.device) либо донора копирования (props.copyFrom). Без источника — пустая
 * форма. Булевы поля приводятся к boolean, остальные — к строке (null → ''). serial_number уникален
 * (UniqueConstraint в backend/app/models.py) — под тем же серийником сохранить копию не получится, заставляем ввести новый явно.
 */
export function deviceFormFromSource(source: Device | null, isCopy: boolean): DeviceForm {
  const next = emptyDeviceForm()
  if (!source) return next
  for (const key of Object.keys(next) as (keyof DeviceForm)[]) {
    const value = source[key as keyof Device]
    if (typeof next[key] === 'boolean') {
      ;(next[key] as boolean) = Boolean(value)
    } else {
      ;(next[key] as string) = (value as string) ?? ''
    }
  }
  if (isCopy) next.serial_number = ''
  return next
}

/** Тело запроса: пустые строки уходят как null; extra (флаги подтверждения конфликтов) дописывается поверх. */
export function deviceFormPayload(form: DeviceForm, extra?: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return { ...payload, ...extra }
}

export function toSoftwareDraftRow(x: DeployedSoftware): SoftwareAssetDraftRow {
  return { id: x.id, software_asset_id: x.software_asset_id, version: x.version ?? '' }
}

export function toDeviceVlanDraftRow(x: DeviceVLAN): DeviceVlanDraftRow {
  return {
    id: x.id,
    vlan_id: x.vlan_id,
    ip_address: x.ip_address ?? '',
    prefix_length: x.prefix_length == null ? '' : String(x.prefix_length),
    is_management: x.is_management,
    description: x.description ?? '',
  }
}

/** Набор VLAN устройства при открытии формы и в черновике: порядок строк не важен, пустые строки не считаются. */
export function deviceVlanKey(rows: readonly DeviceVlanDraftRow[]): string {
  return rows
    .filter((row) => row.vlan_id)
    .map((row) => row.vlan_id)
    .sort()
    .join('|')
}

/**
 * Порты донора для копии: каждая вложенная строка должна создаться заново под НОВЫМ устройством, а не обновить запись донора —
 * id донора означал бы «обновить эту же запись», и backend/app/services/crud/interfaces.py:sync_interfaces отклонил бы его 422
 * «не принадлежит выбранному устройству». Открытые порты и подинтерфейсы — тот же принцип на уровень глубже (как и ips).
 * Копия — новое устройство без подключений (connection: null).
 */
export function copyInterfaceRows(rows: readonly InterfaceDraftRow[]): InterfaceDraftRow[] {
  return rows.map((r) => ({
    ...r,
    id: undefined,
    ips: stripIds(r.ips),
    open_ports: stripIds(r.open_ports),
    subinterfaces: stripSubinterfaceIds(r.subinterfaces),
    connection: null,
  }))
}

export interface ModelGroup {
  manufacturerId: string
  manufacturerName: string
  models: DeviceModel[]
}

/**
 * Модели устройств по производителям: группы — по названию производителя, модели внутри — по названию (ru-локаль).
 * manufacturerName — подпись производителя по его id (null/пусто — «Без производителя»).
 */
export function groupModelsByManufacturer(models: readonly DeviceModel[], manufacturerName: (id: string | null) => string): ModelGroup[] {
  const groups = new Map<string, ModelGroup>()
  for (const m of models) {
    const key = m.manufacturer_id ?? ''
    if (!groups.has(key)) groups.set(key, { manufacturerId: key, manufacturerName: manufacturerName(m.manufacturer_id), models: [] })
    groups.get(key)!.models.push(m)
  }
  return [...groups.values()]
    .map((g) => ({ ...g, models: [...g.models].sort((a, b) => a.model.localeCompare(b.model, 'ru')) }))
    .sort((a, b) => a.manufacturerName.localeCompare(b.manufacturerName, 'ru'))
}

// Фикс п.1.3.7: option внутри optgroup показывал только "голую" модель (WS-C2960-48TD-L) — это
// нормально смотрится, ПОКА список открыт (производитель виден как заголовок группы), но после
// выбора закрытый select показывает ТОЛЬКО текст выбранного option — заголовок optgroup при этом
// не отображается нигде. В закрытом виде терялось "какой это производитель" (напр. WS-C2960-48TD-L
// с равным успехом мог быть и Cisco, и OEM-реброндингом другого вендора). Префикс производителя
// прямо в тексте option чинит именно это, optgroup-группировку при этом не убираем — она всё ещё
// упрощает поиск глазами по алфавиту производителей, пока список открыт.
export function modelOptionLabel(group: Pick<ModelGroup, 'manufacturerId' | 'manufacturerName'>, model: DeviceModel): string {
  return group.manufacturerId ? `${group.manufacturerName} ${model.model}` : model.model
}

/** Опция SearchableSelect.vue (components/SearchableSelect.vue: SearchableSelectOption) — форма та же, без зависимости util от компонента. */
export interface TypeModelOption {
  value: string
  label: string
  group: string
  searchText?: string
}

export const TYPE_WITHOUT_MODEL_GROUP = 'Тип устройства (без конкретной модели)'

/**
 * Опции поля «Тип / производитель / модель»: сначала модели по производителям (заведённые пользователем), в самом конце —
 * «голые» типы без модели. Модель находится и по производителю с названием (они в подписи), и по названию её типа устройства
 * (searchText — в списке не показывается). Значения закодированы как "model:<id>" / "type:<id>": один и тот же id мог бы иначе
 * совпасть между разными сущностями.
 */
export function buildTypeModelOptions(
  groups: readonly ModelGroup[],
  types: readonly { id: string; name: string }[],
  typeLabel: (deviceTypeId: string) => string,
): TypeModelOption[] {
  const models = groups.flatMap((g) =>
    g.models.map((m) => ({ value: `model:${m.id}`, label: modelOptionLabel(g, m), group: g.manufacturerName, searchText: typeLabel(m.device_type_id) })),
  )
  const typeOptions = types.map((t) => ({ value: `type:${t.id}`, label: t.name, group: TYPE_WITHOUT_MODEL_GROUP }))
  return [...models, ...typeOptions]
}

/** Значение поля «Тип / производитель / модель» по форме: модель, иначе тип, иначе пусто. */
export function typeModelValue(form: Pick<DeviceForm, 'model_id' | 'device_type_id'>): string {
  if (form.model_id) return `model:${form.model_id}`
  if (form.device_type_id) return `type:${form.device_type_id}`
  return ''
}

/**
 * Поля формы, которые меняет выбор в поле «Тип / производитель / модель». Выбор модели переносит в форму её тип и производителя,
 * выбор «голого» типа — сбрасывает модель и производителя, пустой выбор — все три. value может прийти undefined: рантайм-директива
 * vModelSelect у Vue берёт value ПЕРВОЙ выбранной option — если ни одна не выбрана, массив выбранных пуст и selectedVal[0]
 * оказывается undefined.
 */
export function typeModelPatch(
  value: string | undefined,
  models: readonly DeviceModel[],
  currentTypeId: string,
): Pick<DeviceForm, 'model_id' | 'device_type_id' | 'manufacturer_id'> {
  const [kind, id] = (value ?? '').split(':')
  if (kind === 'model') {
    const model = models.find((m) => m.id === id)
    return { model_id: id, device_type_id: model?.device_type_id ?? currentTypeId, manufacturer_id: model?.manufacturer_id ?? '' }
  }
  if (kind === 'type') return { model_id: '', device_type_id: id, manufacturer_id: '' }
  return { model_id: '', device_type_id: '', manufacturer_id: '' }
}
