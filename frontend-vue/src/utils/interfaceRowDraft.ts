// Черновые строки редактора портов (components/DeviceInterfacesEditor.vue): новая строка, генерация по шаблону имени,
// переименование порта и очистка ссылок на удалённые строки. Чистые функции — без Vue, сторов и доступа к props компонента.
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'
import { newRowKey, peerRef, rowRef } from './interfaceConnections'
import { renameSubinterfacesForPort } from './subinterfaces'

/** Шаблон имени порта, если поле шаблона оставили пустым. */
export const DEFAULT_NAME_TEMPLATE = 'eth{n}'

export const TEMPLATE_HELP_TEXT =
  'В шаблоне можно использовать:\n' +
  '{n} — порядковый номер порта: 1, 2, 3…\n' +
  '{n0} — тот же номер с ведущим нулём: 01, 02, 03…\n\n' +
  'Примеры:\n' +
  'eth{n} → eth1, eth2, eth3…\n' +
  'GigabitEthernet0/{n0} → GigabitEthernet0/01, GigabitEthernet0/02…\n\n' +
  'Номер отсчитывается от 1 в пределах одного нажатия (при "Заменить все порты" выключено — от '
  + 'количества уже существующих интерфейсов), если поле "Начать нумерацию с" пустое.\n\n' +
  'Нумерация с определённого до определённого номера: заполните "Начать нумерацию с" явным '
  + 'числом — например, "Количество: 20" и "Начать с: 5" сгенерируют порты с номерами 5-24 '
  + '(GigabitEthernet0/5 … GigabitEthernet0/24 для шаблона GigabitEthernet0/{n}).'

/** Пустая строка нового порта. `withKey` — у строки есть ключ, чтобы подключение другого порта могло сослаться на неё, пока у неё нет id. */
export function emptyInterfaceRow(withKey: boolean): InterfaceDraftRow {
  return {
    ...(withKey ? { key: newRowKey() } : {}),
    name: '',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    all_vlans: false,
    // access по умолчанию — п.1.3.1 ("'Режим порта' по умолчанию должен быть 'Access'"). Инференс режима для СТРОК, УЖЕ
    // ЗАГРУЖЕННЫХ из БД (в т.ч. исторических с mode=null), — отдельная логика в
    // api/deviceInterfaces.ts:loadDeviceInterfaceDraftRows: менять её означало бы на лету менять трактовку уже сохранённых связей.
    vlan_mode: 'access',
    ips: [],
    open_ports: [],
    // subinterfaces у новой строки намеренно нет: undefined = «не трогали» (на сервер не уходит), список
    // появляется, когда пользователь добавил первый подинтерфейс (см. InterfaceSubinterfacesEditor).
  }
}

/** Имя порта по шаблону: `{n}` — номер, `{n0}` — номер с ведущим нулём. */
export function applyTemplate(template: string, n: number): string {
  return template.replaceAll('{n}', String(n)).replaceAll('{n0}', String(n).padStart(2, '0'))
}

/**
 * Номер, с которого начинается нумерация в генераторе: явно заданный пользователем переопределяет умолчание.
 * Пустое поле (стёрли значение) — «не задано», а не 0. Значение может быть как строкой, так и числом: v-model на
 * `<input type="number">` в Vue 3 сам приводит валидное число к Number.
 */
export function resolveStartNumber(raw: string | number | null | undefined, defaultStart: number): number {
  if (raw === '' || raw === null || raw === undefined) return defaultStart
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : defaultStart
}

/** Новое имя порта вместе с подинтерфейсами: их автоимена («Gi0/0.10») следуют за именем порта («Gi0/1.10»), а имена,
 * введённые вручную, остаются как есть (utils/subinterfaces.ts:renameSubinterfacesForPort). Без подинтерфейсов или
 * если пересчитывать нечего — только имя; ключ subinterfaces тогда не появляется («не трогали» остаётся «не трогали»). */
export function portNamePatch(row: InterfaceDraftRow, name: string, knownVlans: readonly VLANDefinition[]): Partial<InterfaceDraftRow> {
  if (!row.subinterfaces?.length) return { name }
  const subinterfaces = renameSubinterfacesForPort(row.subinterfaces, row.name, name, knownVlans)
  return subinterfaces === row.subinterfaces ? { name } : { name, subinterfaces }
}

export interface GeneratorSettings {
  count: number
  startNumber: number
  nameTemplate: string
  typeId: string
  speedId: string
}

/**
 * Режим «Заменить все порты»: `count` строк, где существующие строки по индексу СОХРАНЯЮТ id, IP, VLAN и прочее (повторное
 * нажатие с другим количеством не должно рвать связь с уже сохранёнными портами), а имя берётся из шаблона. Тип и скорость,
 * оставленные «— не выбрано —», не затирают значения существующих строк — пустое поле трактуется как «не менять».
 */
export function replaceWithGenerated(existing: readonly InterfaceDraftRow[], settings: GeneratorSettings, knownVlans: readonly VLANDefinition[], makeEmptyRow: () => InterfaceDraftRow): InterfaceDraftRow[] {
  const { count, startNumber, nameTemplate, typeId, speedId } = settings
  return Array.from({ length: count }, (_, i) => {
    const row = existing[i] ?? makeEmptyRow()
    return {
      ...row,
      ...portNamePatch(row, applyTemplate(nameTemplate || DEFAULT_NAME_TEMPLATE, startNumber + i), knownVlans),
      interface_type_id: typeId || row.interface_type_id,
      speed_id: speedId || row.speed_id,
    }
  })
}

/** Режим «Дополнить»: `count` НОВЫХ строк, существующие не затрагиваются вовсе. */
export function generateNewRows(settings: GeneratorSettings, makeEmptyRow: () => InterfaceDraftRow): InterfaceDraftRow[] {
  const { count, startNumber, nameTemplate, typeId, speedId } = settings
  return Array.from({ length: count }, (_, i) => ({
    ...makeEmptyRow(),
    name: applyTemplate(nameTemplate || DEFAULT_NAME_TEMPLATE, startNumber + i),
    interface_type_id: typeId,
    speed_id: speedId,
  }))
}

/** Строки удалены: подключения других портов, ссылавшиеся на них, теряют соседа (форма потребует выбрать
 * другого или нажать «Отключить»), а не уходят на сервер с несуществующей ссылкой. */
export function clearReferencesTo(rows: InterfaceDraftRow[], removed: readonly InterfaceDraftRow[]): InterfaceDraftRow[] {
  const refs = new Set(removed.map(rowRef).filter(Boolean))
  if (!refs.size) return rows
  return rows.map((r) => {
    if (!r.connection || !refs.has(peerRef(r.connection))) return r
    const connection = { ...r.connection, peer_interface_id: '' }
    delete connection.peer_row_key
    return { ...r, connection }
  })
}
