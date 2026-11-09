// Общая логика загрузки/сохранения интерфейсов (портов) физического устройства.
//
// Раньше жила только внутри DeviceFormModal.vue. Вынесена в отдельный модуль, чтобы её же
// переиспользовал DevicePortsModal.vue — управление портами прямо с экрана «Подключения»
// (см. frontend-vue/README.md: было в «Ещё не сделано», теперь реализовано). Обе точки входа
// используют один и тот же атомарный эндпоинт PUT /devices/{id}/interfaces (см.
// backend/app/services/crud/interfaces.py:sync_interfaces) — он одним запросом создаёт/обновляет/удаляет
// набор интерфейсов и их IP по diff'у с тем, что уже есть в БД, поэтому здесь нет отдельных
// create/update/delete-функций, только load+persist целиком.
import { api, listAllResource } from './client'
import type {
  DeviceInterface,
  DeviceSubinterface,
  IPAddress,
  InterfaceGroup,
  InterfaceGroupDraft,
  InterfaceVlansEntry,
  InterfaceDraftRow,
  OpenPort,
  ProtocolPortCatalogEntry,
} from './types'

/**
 * Грузит интерфейсы одного устройства вместе с их IP и VLAN-привязками и приводит к формату
 * InterfaceDraftRow, который понимает DeviceInterfacesEditor.vue.
 *
 * IP и открытые порты портов читаются запросами ПО УСТРОЙСТВУ (GET /devices/{id}/interface-ips и
 * /interface-open-ports) одним запросом на всё устройство, а не generic-списками по owner_type: те отдают не
 * больше 1000 записей реестра (oldest-first), и когда строк у портов всех устройств больше 1000, строки свежих
 * портов отрезались — форма открывалась без их IP и открытых портов, а повторное сохранение удаляло их из БД.
 *
 * VLAN портов читаются запросом ПО УСТРОЙСТВУ (GET /devices/{id}/interface-vlans), а не общим списком
 * связей реестра: тот отдаёт не больше 1000 записей (oldest-first), и когда в реестре больше 1000
 * связей, связи свежих портов отрезались — порт открывался с 0 VLAN, а повторное сохранение удаляло
 * их из БД. Запрос устройства возвращает и признак «Все VLAN» (all_vlans), и VLAN порта с его учётом:
 * у порта с признаком связей в БД нет, набор — все VLAN устройства.
 *
 * @example
 * const rows = await loadDeviceInterfaceDraftRows('dev-123')
 */
export async function loadDeviceInterfaceDraftRows(deviceId: string): Promise<InterfaceDraftRow[]> {
  const [ifaces, allIps, portVlans, allOpenPorts, subinterfaces] = await Promise.all([
    listAllResource<DeviceInterface>('interfaces', { physical_device_id: deviceId }),
    api.get<{ items: IPAddress[] }>(`/devices/${deviceId}/interface-ips`),
    api.get<{ items: InterfaceVlansEntry[] }>(`/devices/${deviceId}/interface-vlans`),
    // Фикс п.1.4 (батч4): открытые порты — теперь свойство интерфейса (owner_type=
    // 'device_interface', owner_id=id интерфейса), не всего устройства, см. комментарий к
    // InterfaceDraftRow.open_ports в api/types/interfaces.ts и backend/app/services/crud/interfaces.py:
    // _sync_interface_open_ports. Читаются по устройству, как IP и VLAN выше.
    api.get<{ items: OpenPort[] }>(`/devices/${deviceId}/interface-open-ports`),
    // Подинтерфейсы портов — тоже одним запросом по устройству, уже с их IP и открытыми портами: подинтерфейс
    // не физический порт и в generic-списке портов его нет.
    api.get<{ items: DeviceSubinterface[] }>(`/devices/${deviceId}/subinterfaces`),
  ])
  const subinterfacesByParent = groupSubinterfacesByParent(subinterfaces.items)
  const vlansByPort = new Map(portVlans.items.map((entry) => [entry.interface_id, entry]))
  return ifaces.items.map((x): InterfaceDraftRow => {
    const vlans = vlansByPort.get(x.id)
    return {
      id: x.id,
      name: x.name,
      interface_type_id: x.interface_type_id ?? '',
      mac_address: x.mac_address ?? '',
      speed_id: x.speed_id ?? '',
      is_management: x.is_management,
      is_data_transfer: x.is_data_transfer,
      description: x.description ?? '',
      vlan_ids: vlans ? [...vlans.vlan_ids] : [],
      // «Все VLAN» — сохранённый признак порта, а не вывод из числа VLAN (vlan_ids у такого порта — все VLAN устройства).
      all_vlans: vlans?.all_vlans ?? false,
      // Фикс п.1.3.9: раньше режим порта выводился из InterfaceVLAN.mode ("trunk", если связей
      // нет или их mode не везде 'access') — при 0 VLAN на порту связей не было вовсе, и
      // access-режим без выбранного VLAN откатывался в trunk после каждого сохранения+
      // перезагрузки формы. Теперь режим читается напрямую с самого интерфейса
      // (DeviceInterface.vlan_mode, backend/app/models.py) — источник истины, не вывод.
      vlan_mode: x.vlan_mode,
      // Принадлежность порта группе: ключ группы = её id (см. InterfaceGroupDraft.key).
      group_key: x.group_id ?? '',
      subinterfaces: subinterfacesByParent.get(x.id) ?? [],
      ips: allIps.items
        .filter((ip) => ip.owner_id === x.id)
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address,
          prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length),
          purpose: ip.purpose ?? '',
        })),
      open_ports: allOpenPorts.items
        .filter((p) => p.owner_id === x.id)
        .sort((a, b) => a.port - b.port)
        .map((p) => ({
          id: p.id,
          protocol_catalog_id: p.protocol_catalog_id ?? '',
          transport_protocol: p.transport_protocol,
          description: p.description ?? '',
        })),
    }
  })
}

/**
 * Грузит группы портов устройства (GET /devices/{id}/interface-groups) в формате черновика
 * InterfaceGroupDraft для DeviceInterfacesEditor.vue: ключ сохранённой группы равен её id, пустые
 * необязательные значения превращаются в '' (как у остальных полей формы).
 *
 * @example
 * const groups = await loadDeviceInterfaceGroups('dev-123')
 */
export async function loadDeviceInterfaceGroups(deviceId: string): Promise<InterfaceGroupDraft[]> {
  const { items } = await api.get<{ items: InterfaceGroup[] }>(`/devices/${deviceId}/interface-groups`)
  return items.map(toGroupDraft)
}

function toGroupDraft(g: InterfaceGroup): InterfaceGroupDraft {
  return {
    id: g.id,
    key: g.id,
    name: g.name,
    vlan_mode: g.vlan_mode ?? '',
    vlan_ids: [...g.vlan_ids],
    all_vlans: g.all_vlans ?? false,
    ips: (g.ips ?? []).map((ip) => ({
      id: ip.id,
      ip_address: ip.ip_address,
      prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length),
      purpose: ip.purpose ?? '',
    })),
    manage_open_ports: g.manage_open_ports,
    open_ports: g.open_ports.map((p) => ({
      id: p.id,
      protocol_catalog_id: p.protocol_catalog_id,
      transport_protocol: p.transport_protocol,
      description: p.description ?? '',
    })),
    manage_subinterfaces: g.manage_subinterfaces ?? false,
    subinterfaces: (g.subinterfaces ?? []).map(toGroupSubinterfaceDraftRow),
  }
}

import { isValidIPv4, isValidPrefixLength } from '../utils/ipValidation'
import { duplicatePortNumbers } from '../utils/openPorts'
import { connectionPayload, type ConnectionBaseline } from '../utils/interfaceConnections'
import {
  groupSubinterfacesByParent,
  groupSubinterfacesPayload,
  subinterfacesPayload,
  toGroupSubinterfaceDraftRow,
  validateSubinterfaceRows,
} from '../utils/subinterfaces'

/** У каждого интерфейса должно быть имя — бэкенд это тоже проверит (422), но лучше показать
 * понятную ошибку до запроса, чем ждать round-trip. UI (DeviceInterfacesEditor.vue) не даёт
 * набрать больше одного VLAN в режиме access, но проверка здесь — защита на случай данных,
 * загруженных из БД в уже несогласованном виде (см. комментарий к InterfaceDraftRow.vlan_mode).
 * Возвращает текст ошибки либо null. portCatalog — справочник «порт + протокол» (catalogs.protocolPortCatalog),
 * нужен для проверки повторов номеров открытых портов. allowedVlanIds — VLAN, доступные устройству (опции VLAN
 * порта формы): подинтерфейс на другом VLAN блокирует сохранение (необязателен — DevicePortsModal списка не знает).
 *
 * Фикс п.2.1.3: IP-адреса/префиксы интерфейса (InterfaceDraftRow.ips) — та же причина, что и у
 * остальных проверок здесь: показать понятную ошибку сразу, а не ждать 422 с бэкенда. */
export function validateInterfaceDraftRows(
  rows: InterfaceDraftRow[],
  portCatalog: readonly ProtocolPortCatalogEntry[] = [],
  allowedVlanIds?: ReadonlySet<string>,
): string | null {
  if (rows.some((row) => !row.name.trim())) return 'У каждого интерфейса должно быть имя.'
  if (rows.some((row) => row.vlan_mode === 'access' && row.vlan_ids.length > 1)) {
    return 'В режиме access у порта может быть не более одного VLAN.'
  }
  for (const row of rows) {
    for (const ip of row.ips) {
      if (!isValidIPv4(ip.ip_address)) return `Некорректный IP-адрес «${ip.ip_address}» на порту «${row.name}».`
      if (!isValidPrefixLength(ip.prefix_length)) return `Некорректный префикс «${ip.prefix_length}» на порту «${row.name}» — допустимо 0-32.`
    }
    // Номера открытых портов одного порта устройства не повторяются (то же правило, что в форме ВМ,
    // см. utils/openPorts.ts). Без каталога (portCatalog не передан) номер не определить — проверка
    // пропускается, остаётся серверная (backend/app/services/validation.py).
    const duplicates = duplicatePortNumbers(row.open_ports, portCatalog)
    if (duplicates.length) return `На порту «${row.name}» номера открытых портов повторяются: ${duplicates.join(', ')}.`
    // Фикс "убрать текстовые поля Порт/Протокол": раньше здесь же проверялся номер открытого
    // порта (свободный текст, введённый вручную) — с тех пор, как единственный вход стал
    // protocol_catalog_id (значение из справочника, а не текст), проверять на этом уровне
    // больше нечего: несуществующую ссылку отклонит сервер (422), а пустую строку без выбора
    // тихо пропускает toApiPayload() (см. её комментарий) — как и раньше с пустым номером порта.
  }
  // Подинтерфейсы портов: имя и VLAN обязательны, имена уникальны на устройстве, VLAN на порту один раз;
  // с allowedVlanIds — ещё и VLAN должен быть доступен устройству (см. validateSubinterfaceRows).
  return validateSubinterfaceRows(rows, portCatalog, allowedVlanIds)
}

/**
 * Сохраняет набор интерфейсов устройства через атомарный PUT. vlan_ids и all_vlans каждого ряда отправляются
 * как пришли из loadDeviceInterfaceDraftRows (см. комментарий к InterfaceDraftRow в api/types/interfaces.ts) —
 * если вызывающий компонент их не редактирует (как DevicePortsModal.vue), они просто
 * round-trip'ятся туда-обратно неизменными и НЕ стираются молча. vlan_mode round-trip'ится по
 * тому же принципу (п.1.4.3.2).
 *
 * Чистый API-вызов: НЕ обновляет catalogs.items['interfaces'] сама — этот модуль намеренно не
 * знает про Pinia-сторы (см. комментарий в шапке файла). Вызывающая сторона обязана сама
 * прогнать результат через catalogs.replaceDeviceInterfaces(deviceId, items) — иначе другие
 * компоненты, читающие этот кэш (напр. поле "Порт" в ConnectionFormModal.vue), продолжат
 * видеть старые данные до перезагрузки страницы. Забыли сделать это в DeviceFormModal.vue —
 * фикс п.3.1; DevicePortsModal.vue делал это с самого начала, см. её submit().
 *
 * connectionBaseline — снимок подключений портов на момент загрузки формы (utils/interfaceConnections.ts:
 * snapshotConnections); передаётся ТОЛЬКО вызывающей стороной, которая их редактирует (как groups). Тогда
 * в ключе `connection` каждого порта уходит лишь изменённое подключение (объект — создать/обновить, null —
 * отключить), а у нетронутых портов ключа нет — сервер их подключения не трогает. Новый порт (без id) с
 * подключением тоже отправляется: сервер создаёт его в той же транзакции, что и сам порт.
 *
 * @example
 * const { items } = await persistDeviceInterfaces('dev-123', rows)
 * catalogs.replaceDeviceInterfaces('dev-123', items)
 */
export async function persistDeviceInterfaces(
  deviceId: string,
  rows: InterfaceDraftRow[],
  groups?: InterfaceGroupDraft[],
  connectionBaseline?: ConnectionBaseline,
): Promise<{ items: DeviceInterface[]; groups: InterfaceGroup[] }> {
  return api.put<{ items: DeviceInterface[]; groups: InterfaceGroup[] }>(`/devices/${deviceId}/interfaces`, {
    // Группы портов: groups передаётся ТОЛЬКО вызывающей стороной, которая их редактирует, и тогда
    // это полный список групп устройства (в т.ч. пустой — «групп нет», сервер удалит прежние).
    // Без groups ключа в запросе нет вовсе — сервер не трогает ни группы, ни членство портов.
    ...(groups
      ? {
          groups: groups.map((g) => ({
            id: g.id,
            key: g.key,
            name: g.name.trim(),
            vlan_mode: g.vlan_mode || null,
            // «Все VLAN» только в trunk; с признаком сервер хранит лишь его (vlan_ids игнорируется).
            all_vlans: g.vlan_mode === 'trunk' && g.all_vlans === true,
            vlan_ids: g.vlan_mode ? g.vlan_ids : [],
            // Общие IP группы — полный список; строка без адреса (плейсхолдер формы) не уходит.
            ips: g.ips
              .filter((ip) => ip.ip_address.trim())
              .map((ip) => ({
                id: ip.id,
                ip_address: ip.ip_address.trim(),
                prefix_length: ip.prefix_length !== '' ? Number(ip.prefix_length) : null,
                purpose: ip.purpose.trim() || null,
              })),
            manage_open_ports: g.manage_open_ports,
            open_ports: g.manage_open_ports
              ? g.open_ports
                  .filter((p) => p.protocol_catalog_id)
                  .map((p) => ({
                    id: p.id,
                    protocol_catalog_id: p.protocol_catalog_id,
                    transport_protocol: p.transport_protocol || 'TCP',
                    description: p.description || null,
                  }))
              : [],
            // Подинтерфейсы группы — полный список, пока группа ими управляет (пустой тоже значение); без признака не уходят.
            manage_subinterfaces: g.manage_subinterfaces === true,
            subinterfaces: g.manage_subinterfaces === true && g.vlan_mode ? groupSubinterfacesPayload(g.subinterfaces ?? []) : [],
          })),
        }
      : {}),
    interfaces: rows.map((row) => ({
      id: row.id,
      ...(groups ? { group_key: row.group_key || null } : {}),
      ...connectionEntry(row, connectionBaseline, rows),
      name: row.name.trim(),
      interface_type_id: row.interface_type_id || null,
      mac_address: row.mac_address || null,
      speed_id: row.speed_id || null,
      is_management: row.is_management,
      is_data_transfer: row.is_data_transfer,
      description: row.description || null,
      vlan_ids: row.vlan_ids,
      vlan_mode: row.vlan_mode,
      // Признак «Все VLAN» уходит ВСЕГДА (в том числе false): ключа нет — сервер читает это как «выбраны вручную».
      // В access он невозможен и не отправляется как true.
      all_vlans: row.vlan_mode === 'trunk' && row.all_vlans === true,
      ips: row.ips
        .filter((ip) => ip.ip_address.trim())
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address.trim(),
          prefix_length: ip.prefix_length === '' ? null : Number(ip.prefix_length),
          purpose: ip.purpose || null,
        })),
      // Подинтерфейсы порта — полный список (в т.ч. пустой: «подинтерфейсов нет», сервер удалит прежние). Ключа нет
      // у строк, чьи подинтерфейсы форма не загружала (subinterfaces не задано): сервер их не трогает.
      ...(row.subinterfaces ? { subinterfaces: subinterfacesPayload(row.subinterfaces) } : {}),
      // Фикс п.1.4 (батч4): открытые порты round-trip'ятся вместе со своим интерфейсом в том же
      // атомарном PUT — см. backend/app/services/crud/interfaces.py:_sync_interface_open_ports. Правка
      // "убрать текстовые поля Порт/Протокол": строка без выбранной записи справочника (после
      // добавления "+ Открытый порт", пока пользователь ещё ничего не выбрал) пропускается так
      // же, как раньше пустой port; port/protocol в payload не отправляем вовсе — сервер сам
      // выведет их из protocol_catalog_id.
      open_ports: row.open_ports
        .filter((p) => p.protocol_catalog_id)
        .map((p) => ({
          id: p.id,
          protocol_catalog_id: p.protocol_catalog_id,
          transport_protocol: p.transport_protocol || 'TCP',
          description: p.description || null,
        })),
    })),
  })
}

/** Ключ `connection` элемента payload: пусто, если подключения не редактируются или порт не менялся. */
function connectionEntry(
  row: InterfaceDraftRow,
  baseline: ConnectionBaseline | undefined,
  rows: readonly InterfaceDraftRow[],
): { connection?: ReturnType<typeof connectionPayload> } {
  if (!baseline) return {}
  const value = connectionPayload(row, baseline, rows)
  return value === undefined ? {} : { connection: value }
}
