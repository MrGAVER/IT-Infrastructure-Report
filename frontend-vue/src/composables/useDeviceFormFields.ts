// Основные поля формы устройства (DeviceMainFields.vue): опции справочников, каскад здание → помещение → стойка, поле
// «Тип / производитель / модель» и синхронизация формы с записями, созданными быстрым добавлением («+»).
import { computed, watch } from 'vue'
import type { CatalogItem, DeviceModel, Rack, Room } from '../api/types'
import type { QuickAddFkScope } from '../quickAdd/schema'
import { useCatalogsStore } from '../stores/catalogs'
import { buildTypeModelOptions, groupModelsByManufacturer, typeModelPatch, typeModelValue, type DeviceForm } from '../utils/deviceForm'

/** form — реактивный объект формы (useDeviceDraft): композибл правит его поля на месте. */
export function useDeviceFormFields(form: DeviceForm) {
  const catalogs = useCatalogsStore()

  // Каскадные списки: помещение — по зданию, стойка — по помещению. Тот же принцип, что связка
  // building_id/room_id в фильтре DevicesView, только здесь ещё и сама форма подсказывает валидные
  // сочетания вместо того, чтобы полагаться только на серверную валидацию.
  const deviceModels = computed(() => catalogs.items['device-models'] as unknown as DeviceModel[])
  const rooms = computed(() => catalogs.items['rooms'] as unknown as Room[])
  const racks = computed(() => catalogs.items['racks'] as unknown as Rack[])

  const filteredRooms = computed(() => (rooms.value ?? []).filter((r) => !form.building_id || r.building_id === form.building_id))
  const filteredRacks = computed(() => (racks.value ?? []).filter((r) => !form.room_id || r.room_id === form.room_id))

  // Фикс п.1.1: поиск вводом текста в "Помещение" (и заодно в соседних Здание/Стойка — те же
  // select'ы в той же карточке, оставлять их нативными при уже поисковом "Помещении" рядом выглядело
  // бы непоследовательно). catalogs.items[key] уже отсортирован (фикс п.4.2) — SearchableSelect
  // сам ничего не пересортировывает, порядок options здесь и есть порядок в выпадающем списке.
  // Пункт 2: поиск вводом текста в "Операционная система" и "Встроенная ОС" — тот же SearchableSelect,
  // что у Здания/Помещения/Стойки выше. Подпись — catalogs.label() ("name version"), порядок — уже
  // отсортированный catalogs.items (см. sortCatalogItems в stores/catalogs.ts).
  const operatingSystemOptions = computed(() =>
    (catalogs.items['operating-systems'] ?? []).map((os) => ({ value: os.id, label: catalogs.label('operating-systems', os.id) })),
  )
  const embeddedOsOptions = computed(() => (catalogs.items['embedded-os'] ?? []).map((os) => ({ value: os.id, label: catalogs.label('embedded-os', os.id) })))
  const buildingOptions = computed(() => (catalogs.items['buildings'] ?? []).map((b) => ({ value: b.id, label: b.name })))
  const roomOptions = computed(() => filteredRooms.value.map((r) => ({ value: r.id, label: r.name })))
  const rackOptions = computed(() => filteredRacks.value.map((r) => ({ value: r.id, label: r.name })))

  // Окно «Добавить: Помещение» из этой формы: поле «Здание» заранее равно зданию, выбранному в форме (не выбрано —
  // пусто). Это стартовое значение, а не блокировка: в окне здание можно сменить.
  const roomQuickAddValues = computed(() => (form.building_id ? { building_id: form.building_id } : undefined))

  // Окно «Добавить: Стойка» из этой формы: список помещений ограничен выбранным зданием (здание не выбрано — полный
  // список), а помещение, уже выбранное в форме, подставлено в окно автоматически. Фильтр работает только на выбор в
  // окне стойки: список «Помещение» самой формы по-прежнему строится от здания (roomOptions).
  const rackQuickAddValues = computed(() => (form.room_id ? { room_id: form.room_id } : undefined))
  const rackQuickAddScope = computed<QuickAddFkScope>(() => ({ room_id: { field: 'building_id', value: form.building_id } }))

  // п.3.6: поля "Тип устройства"/"Производитель"/"Модель" объединены в одно — это ОДИН select с
  // двумя видами опций (группа "без модели" — просто тип, и группы моделей по производителю), а не
  // три отдельных lookup'а.
  //
  // Компромисс этого объединения: раньше можно было явно указать производителя БЕЗ конкретной
  // модели (три независимых поля) — при объединении в одно поле это больше не выразимо, т.к.
  // единственный оставшийся способ задать производителя — выбрать модель, которая его несёт с
  // собой. Это соответствует буквальной формулировке задачи ("одним полем"); если понадобится
  // вернуть возможность "тип + производитель без модели", это отдельное решение, не совместимое с
  // одним select'ом.
  const modelGroups = computed(() =>
    groupModelsByManufacturer(deviceModels.value ?? [], (id) => (id ? catalogs.label('manufacturers', id, 'Без производителя') : 'Без производителя')),
  )

  // Поиск вводом текста в поле «Тип / производитель / модель» (SearchableSelect вместо нативного select).
  const typeModelOptions = computed(() =>
    buildTypeModelOptions(modelGroups.value, catalogs.items['device-types'] ?? [], (typeId) => catalogs.label('device-types', typeId, '')),
  )

  const typeModelSelection = computed<string, string | undefined>({
    get: () => typeModelValue(form),
    set(value) {
      Object.assign(form, typeModelPatch(value, deviceModels.value ?? [], form.device_type_id))
    },
  })

  // Квик-добавление модели устройства подставляет её id и синхронизирует device_type_id и
  // manufacturer_id формы с моделью — то же самое, что делает setter typeModelSelection выше при
  // выборе уже существующей модели, продублировано здесь явно, т.к. QuickAddButton отдаёт "сырой"
  // CatalogItem напрямую в обход этого computed setter'а.
  function onModelCreated(record: CatalogItem) {
    const model = record as unknown as DeviceModel
    form.model_id = model.id
    form.device_type_id = model.device_type_id ?? form.device_type_id
    form.manufacturer_id = model.manufacturer_id ?? ''
  }

  // Сброс зависимых полей при смене родителя — иначе можно оставить room_id от
  // другого здания невидимым в списке, но по-прежнему отправляемым в payload.
  watch(
    () => form.building_id,
    () => {
      if (!filteredRooms.value.some((r) => r.id === form.room_id)) form.room_id = ''
    },
  )
  watch(
    () => form.room_id,
    () => {
      if (!filteredRacks.value.some((r) => r.id === form.rack_id)) form.rack_id = ''
    },
  )

  // п.3.1: квик-добавление помещения/стойки синхронизирует и родительские поля формы — иначе
  // созданная запись могла бы не попасть в filteredRooms/filteredRacks (фильтр по
  // building_id/room_id, см. выше) и пропасть из виду в своём же select'е сразу после создания.
  function onRoomCreated(record: CatalogItem) {
    const room = record as unknown as Room
    form.building_id = room.building_id
    form.room_id = room.id
  }
  function onRackCreated(record: CatalogItem) {
    const rack = record as unknown as Rack
    const room = catalogs.indexOf('rooms').get(rack.room_id) as unknown as Room | undefined
    if (room) form.building_id = room.building_id
    form.room_id = rack.room_id
    form.rack_id = rack.id
  }

  return {
    operatingSystemOptions,
    embeddedOsOptions,
    buildingOptions,
    roomOptions,
    rackOptions,
    roomQuickAddValues,
    rackQuickAddValues,
    rackQuickAddScope,
    typeModelOptions,
    typeModelSelection,
    onModelCreated,
    onRoomCreated,
    onRackCreated,
  }
}
