// Схема полей для быстрого добавления записи справочника прямо из формы (кнопка "+" рядом с
// select'ом) — портировано с quickFields/quickLabels в frontend/static/core.js. Не 1:1 копия:
// вложенное быстрое добавление ВНУТРИ формы быстрого добавления (у device-models в vanilla
// можно добавить тип устройства/производителя, не закрывая модалку создания модели) теперь
// частично перенесено — точечно, через флаг nestedQuickAdd на конкретных fk-полях (см. тип
// QuickField выше), а не для всех fk подряд. Второй уровень вложенности (добавить fk ВНУТРИ
// этой вложенной формы) по-прежнему не поддерживается — редкий сценарий, ради которого не
// стоит городить рекурсивный стек модалок. Также не перенесены предзаполнение fk-полей
// текущими значениями внешней формы (device-models подставлял уже выбранные в основной форме
// тип/производителя) и parent_id для подразделений (иерархия подразделений есть в модели, но
// нигде в новом UI ещё не используется — добавлять работающий только наполовину UI-элемент не
// имеет смысла).
//
// Единственный источник правды по полям — соответствующие SQLAlchemy-модели в
// backend/app/models.py; при добавлении сюда новой записи стоит свериться с ними, а не
// придумывать поля по аналогии.
export type QuickFieldType = 'text' | 'textarea' | 'number' | 'checkbox' | 'fk'

export interface QuickField {
  name: string
  label: string
  type: QuickFieldType
  required: boolean
  /** Только для type='fk' — ключ каталога в CATALOGS (stores/catalogs.ts), откуда берутся опции. */
  fkResource?: string
  /** Только для type='fk'. Показывает кнопку "+" рядом с select'ом — открывает ВЛОЖЕННУЮ
   * QuickAddModal для fkResource, не закрывая текущую форму (см. QuickAddModal.vue: nested-*).
   * Включено точечно для полей, где отсутствие нужного значения в справочнике реально мешает
   * заполнить форму прямо сейчас (device-models: тип устройства/производитель; vlans: домен) —
   * не для всех fk-полей подряд, чтобы не плодить лишние "+" там, где каталог почти наверняка
   * уже полон на момент открытия формы. Второй уровень вложенности (добавить fk ВНУТРИ этой
   * вложенной формы) сознательно не поддерживается — см. фильтр в QuickAddModal.vue. */
  nestedQuickAdd?: boolean
}

export const QUICK_ADD_LABELS: Record<string, string> = {
  'device-types': 'Тип устройства',
  manufacturers: 'Производитель',
  'device-models': 'Модель устройства',
  'os-categories': 'Категория ОС',
  'operating-systems': 'Операционная система',
  'embedded-os': 'Встроенная ОС',
  'interface-types': 'Тип интерфейса',
  'interface-speeds': 'Скорость интерфейса',
  'connection-types': 'Тип подключения',
  'protocol-port-catalog': 'Протокол / порт',
  'support-organizations': 'Организация технической поддержки',
  'support-methods': 'Способ оказания технической поддержки',
  'crypto-protection-means': 'Средство криптографической защиты',
  'software-assets': 'Программный актив',
  departments: 'Подразделение',
  'placement-assets': 'Оборудование / ПО / интерфейс размещения',
  'structural-units': 'Структурная единица',
  buildings: 'Здание',
  rooms: 'Помещение',
  racks: 'Стойка',
  vlans: 'VLAN',
  'vlan-domains': 'Домен VLAN',
}

export const QUICK_ADD_FIELDS: Record<string, QuickField[]> = {
  'device-types': [{ name: 'name', label: 'Наименование', type: 'text', required: true }],
  manufacturers: [{ name: 'name', label: 'Наименование', type: 'text', required: true }],
  'device-models': [
    {
      name: 'device_type_id',
      label: 'Тип устройства',
      type: 'fk',
      required: true,
      fkResource: 'device-types',
      nestedQuickAdd: true,
    },
    {
      name: 'manufacturer_id',
      label: 'Производитель',
      type: 'fk',
      required: true,
      fkResource: 'manufacturers',
      nestedQuickAdd: true,
    },
    { name: 'model', label: 'Модель', type: 'text', required: true },
  ],
  'os-categories': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'operating-systems': [
    { name: 'category_id', label: 'Категория ОС', type: 'fk', required: true, fkResource: 'os-categories' },
    { name: 'name', label: 'Наименование ОС', type: 'text', required: true },
    { name: 'version', label: 'Версия', type: 'text', required: false },
    { name: 'vendor', label: 'Производитель', type: 'text', required: false },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'embedded-os': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'version', label: 'Версия', type: 'text', required: false },
    { name: 'vendor', label: 'Производитель', type: 'text', required: false },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'interface-types': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'interface-speeds': [
    { name: 'name', label: 'Скорость', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'connection-types': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'protocol-port-catalog': [
    { name: 'port', label: 'Номер порта', type: 'number', required: true },
    { name: 'protocol_type', label: 'Тип протокола', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'support-organizations': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'short_name', label: 'Краткое наименование', type: 'text', required: false },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'support-methods': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'crypto-protection-means': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  'software-assets': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'category', label: 'Категория', type: 'text', required: false },
    { name: 'vendor', label: 'Производитель', type: 'text', required: false },
    { name: 'version', label: 'Версия', type: 'text', required: false },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  departments: [{ name: 'name', label: 'Наименование', type: 'text', required: true }],
  'placement-assets': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  // parent_id сюда намеренно не добавлен — та же причина, что для departments выше
  // (см. комментарий в шапке файла): второй уровень вложенных модалок ради быстрого
  // добавления родителя не оправдан, к тому же при редактировании существующей единицы
  // потребовалось бы ещё и исключать саму себя из списка (см. availableParents в
  // StructuralUnitFormModal.vue) — эта логика не переносится на generic-форму.
  'structural-units': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  buildings: [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'address', label: 'Адрес', type: 'text', required: false },
    { name: 'structural_unit_id', label: 'Структурная единица', type: 'fk', required: false, fkResource: 'structural-units' },
  ],
  // building_id обязателен на бэкенде (Room.building_id NOT NULL) — без fk-поля здесь
  // сохранение немедленно падало бы 422 у любого, кто добавит помещение через "+".
  rooms: [
    { name: 'building_id', label: 'Здание', type: 'fk', required: true, fkResource: 'buildings' },
    { name: 'name', label: 'Наименование', type: 'text', required: true },
  ],
  racks: [
    { name: 'room_id', label: 'Помещение', type: 'fk', required: true, fkResource: 'rooms' },
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'height_u', label: 'Высота, U', type: 'number', required: false },
  ],
  vlans: [
    { name: 'vlan_id', label: 'VLAN ID', type: 'number', required: true },
    { name: 'name', label: 'Имя', type: 'text', required: true },
    {
      name: 'domain_id',
      label: 'Домен VLAN',
      type: 'fk',
      required: false,
      fkResource: 'vlan-domains',
      nestedQuickAdd: true,
    },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
  // source_device_id/auto_sync/состав участников сюда намеренно не перенесены — то же
  // решение, что и в шапке VLANDomainFormModal.vue: участников можно добавить только у уже
  // существующего домена, а автосинхронизация — второстепенная настройка полной формы, не
  // нужная для быстрого "завести домен, чтобы привязать к нему VLAN".
  'vlan-domains': [
    { name: 'name', label: 'Наименование', type: 'text', required: true },
    { name: 'description', label: 'Описание', type: 'textarea', required: false },
  ],
}
