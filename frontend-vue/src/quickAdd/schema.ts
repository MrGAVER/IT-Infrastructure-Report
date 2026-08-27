// Схема полей для быстрого добавления записи справочника прямо из формы (кнопка "+" рядом с
// select'ом) — портировано с quickFields/quickLabels в frontend/static/core.js. Не 1:1 копия:
// вложенное быстрое добавление ВНУТРИ формы быстрого добавления (у device-models в vanilla
// можно добавить тип устройства/производителя, не закрывая модалку создания модели) не
// перенесено — второй уровень вложенности модалок ради, по сути, редкого сценария. Также не
// перенесены предзаполнение fk-полей текущими значениями внешней формы (device-models
// подставлял уже выбранные в основной форме тип/производителя) и parent_id для подразделений
// (иерархия подразделений есть в модели, но нигде в новом UI ещё не используется — добавлять
// работающий только наполовину UI-элемент не имеет смысла).
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
}

export const QUICK_ADD_FIELDS: Record<string, QuickField[]> = {
  'device-types': [{ name: 'name', label: 'Наименование', type: 'text', required: true }],
  manufacturers: [{ name: 'name', label: 'Наименование', type: 'text', required: true }],
  'device-models': [
    { name: 'device_type_id', label: 'Тип устройства', type: 'fk', required: true, fkResource: 'device-types' },
    { name: 'manufacturer_id', label: 'Производитель', type: 'fk', required: true, fkResource: 'manufacturers' },
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
}
