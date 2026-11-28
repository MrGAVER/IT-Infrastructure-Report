// Стор справочников: подгружает статичные каталоги (типы устройств, производители,
// здания, помещения, структурные единицы и т.п.) один раз за сессию и резолвит
// id → отображаемое имя для колонок таблиц. Аналог CACHEABLE_LIST_RESOURCES +
// lookupLabel() в прежнем vanilla-фронтенде (удалён в 2.60.0), но с типами
// и явным состоянием загрузки вместо ad-hoc Map-кеша поверх fetch().
import { defineStore } from 'pinia'
import { listAllResource, api, type AllPagesResponse } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { CatalogItem, StructuralUnit, ResourceDescriptor, ProtocolPortCatalogEntry } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

/** Подписи разделов журнала аудита, которых нет в /api/v1/resources (записи о служебных настройках, а не о ресурсах реестра).
 * Раздел 'audit-settings' — изменение срока хранения журнала и очистка по сроку (backend/app/services/audit_retention.py);
 * 'backup-settings' — изменение интервала и числа плановых копий БД (backend/app/services/backup_settings.py);
 * 'consistency-approvals' — одобрение и снятие одобрения проблем проверки данных (backend/app/services/consistency/approvals.py). */
const SERVICE_SECTION_LABELS: Record<string, string> = {
  'audit-settings': 'Настройки аудита',
  'backup-settings': 'Настройки резервных копий',
  'consistency-approvals': 'Одобрения проверки данных',
}

// Сортировка кириллицы регистронезависимо + numeric:true — числа внутри строки сравниваются как
// числа, а не посимвольно ("Gi1/0/2" раньше "Gi1/0/19", а не наоборот, как было бы при обычном
// лексикографическом сравнении — фикс п.3.5 "натуральная сортировка" портов). Тот же collator
// годится и для обычных кириллических названий (буквы/цифры в имени организации и т.п.). Экспортируется
// — та же сортировка нужна и вне этого стора (напр. ConnectionFormModal.vue сортирует список
// устройств из stores/devices.ts, который здесь не живёт), плюс Intl.Collator дороговат
// пересоздавать на каждый вызов — единственный на всё приложение инстанс.
export const RU_COLLATOR = new Intl.Collator('ru', { sensitivity: 'base', numeric: true })

/** Узел дерева структурных единиц — рекурсивно типизированный (см. StructuralUnitTree.vue). */
export interface StructuralUnitNode extends StructuralUnit {
  children: StructuralUnitNode[]
}

// Ресурсы, которые реально используются на экране "Инвентаризация устройств".
// Расширять по мере добавления новых экранов — не грузим то, что не показываем.
// Фикс п.4: 'organizations' удалён отсюда вместе с самим справочником (backend/app/models.py,
// миграция e519c184f3ae) — не путать с настройкой названия организации в шапке
// сайдбара (stores/organization.ts, единственное число) — это два не связанных друг с другом
// "organization".
const CATALOGS = [
  'device-types',
  'device-categories',
  'manufacturers',
  'device-models',
  'diagram-icons',
  'operating-systems',
  'embedded-os',
  'buildings',
  'rooms',
  'racks',
  'structural-units',
  'support-organizations',
  'support-methods',
  'crypto-protection-means',
  'interfaces',
  'connection-types',
  'vlan-domains',
  'software-assets',
  'interface-types',
  'interface-speeds',
  'departments',
  'placement-assets',
  'os-categories',
] as const
type CatalogKey = (typeof CATALOGS)[number]

/** Сортирует список опций каталога так, как он выглядит для пользователя в select'е — фикс п.4.2
 * ("во всех полях с выпадающим текстом на всех формах должна быть применена сортировка").
 * Применяется в ЕДИНСТВЕННОМ месте, где items[key] пишется в стор (reload() и
 * replaceDeviceInterfaces() ниже) — десяткам select'ов по всему приложению, которые просто читают
 * catalogs.items[key] как есть, менять не нужно.
 *
 * Особые случаи, где видимый пользователю текст — не просто item.name (совпадает с ветками в
 * catalogs.label() ниже):
 * - operating-systems/embedded-os показывают "name version" (напр. "Windows Server 2019") —
 *   сортируем по (name, version) раздельно, а не по уже склеенной строке: (name, version) с
 *   numeric-коллатором даёт ожидаемый порядок версий ВНУТРИ одного имени ОС, чего не даст простое
 *   сравнение склеенных строк.
 * - interfaces (порты устройств, поле "Порт" в дашборде "Подключения") — natural sort по name
 *   через тот же numeric-коллатор чинит п.3.5: "Gi1/0/2" перед "Gi1/0/19".
 * - device-models сортируются по .model — сама группировка/сортировка по производителю живёт в
 *   DeviceFormModal.vue (modelGroups), т.к. только там есть под рукой резолвленное имя
 *   производителя; здесь достаточно не оставлять модели внутри группы в порядке ответа бэкенда. */
function sortCatalogItems<T extends CatalogItem>(key: CatalogKey, items: T[]): T[] {
  if (key === 'operating-systems' || key === 'embedded-os') {
    return [...items].sort((a, b) => RU_COLLATOR.compare(a.name, b.name) || RU_COLLATOR.compare(String(a.version ?? ''), String(b.version ?? '')))
  }
  if (key === 'device-models') {
    return [...items].sort((a, b) => RU_COLLATOR.compare(String(a.model ?? ''), String(b.model ?? '')))
  }
  return [...items].sort((a, b) => RU_COLLATOR.compare(a.name, b.name))
}

/** Сортирует справочник «Протоколы и порты» численно по port, затем по protocol_type — тот же
 * принцип "во всех полях с выпадающим текстом должна быть сортировка" (фикс п.4.2), что и
 * sortCatalogItems() выше, но отдельной функцией: у записи нет поля name (см. комментарий к
 * protocolPortCatalog в state ниже), поэтому она не входит в CATALOGS/sortCatalogItems.
 * Экспортируется: нужна и вне этого стора — QuickAddModal.vue пересортировывает локально после
 * создания новой записи через "+" (см. её комментарий), не дожидаясь полного reload(). */
export function sortProtocolPortCatalog(items: ProtocolPortCatalogEntry[]): ProtocolPortCatalogEntry[] {
  return [...items].sort((a, b) => a.port - b.port || a.protocol_type.localeCompare(b.protocol_type, 'ru'))
}

// Ответ на более ранний reload() не должен затереть более поздний или точечное изменение каталога (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useCatalogsStore = defineStore('catalogs', {
  state: () => ({
    items: {} as Record<CatalogKey, CatalogItem[]>,
    resourceNames: {} as Record<string, string>,
    // Отдельно от items/CATALOGS: у ProtocolPortCatalogEntry нет поля name, поэтому
    // он не подходит под общий Record<CatalogKey, CatalogItem[]> (см. комментарий
    // к типу в api/types). Используется в OpenPortListEditor.vue.
    protocolPortCatalog: [] as ProtocolPortCatalogEntry[],
    // B-02: справочники, загруженные не целиком (потолок listAllResource, 50 000 записей): ключ → сколько получено и сколько на сервере.
    // Справочники не блокируют сохранение (формы не пишут их целиком), но экран, показывающий справочник полностью, обязан сказать, что
    // видна только часть: постоянно (DataLoadNotice), а не только исчезающим через 10 с предупреждением.
    incompleteCatalogs: {} as Record<string, { loaded: number; total: number }>,
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    /** Человекочитаемое имя ресурса (DISPLAY_NAMES на бэкенде) — для entity_type в
     * журнале аудита. Не хардкодим словарь во фронтенде — грузим с /api/v1/resources,
     * чтобы не расходиться с бэкендом при добавлении новых ресурсов. */
    resourceLabel:
      (state) =>
      (key: string): string =>
        state.resourceNames[key] ?? SERVICE_SECTION_LABELS[key] ?? key,
    /** Быстрый лукап id → запись для конкретного каталога.
     *
     * Кеш индекса намеренно ключуется по САМОМУ МАССИВУ (WeakMap), а не по имени каталога, как
     * было раньше (баг): reload()/QuickAddModal всегда присваивают items[key] НОВЫЙ массив,
     * никогда не мутируют старый. Если бы кеш жил по имени каталога, первый же вызов indexOf(key)
     * до того, как items[key] заполнился (обычная гонка — компонент уже отрендерился, а
     * catalogs.reload() ещё не резолвнулся), навсегда запирал бы пустой Map на этот ключ:
     * state.items[key] к моменту повторных вызовов давно новый и
     * заполненный, но cache.get(key) находил бы старую пустую запись и просто возвращал её, не
     * заглядывая в state заново. Внешне это выглядело как "новая запись каталога висит '—' до
     * перезагрузки страницы" (см. QUICK_ADD созданные записи в DeviceFormModal.vue) — заводили её
     * не через reload() тем же тиком, а раньше он уже успел закешировать пустоту. WeakMap же
     * ключуется по ссылке на массив: старый (пустой) массив просто перестаёт быть кем-либо
     * востребован и вымывается GC, а новый массив — новый ключ, новый (корректный) индекс. */
    indexOf: (state) => {
      const cache = new WeakMap<CatalogItem[], Map<string, CatalogItem>>()
      return (key: CatalogKey): Map<string, CatalogItem> => {
        const list = state.items[key] ?? []
        let idx = cache.get(list)
        if (!idx) {
          idx = new Map(list.map((it) => [it.id, it]))
          cache.set(list, idx)
        }
        return idx
      }
    },
    structuralUnits: (state): StructuralUnit[] => (state.items['structural-units'] as StructuralUnit[]) ?? [],
    /** Дерево структурных единиц: parent_id === null — корень (тот же паттерн, что Department). */
    structuralUnitTree(): StructuralUnitNode[] {
      const all = this.structuralUnits
      const byParent = new Map<string | null, StructuralUnit[]>()
      for (const u of all) {
        const key = u.parent_id ?? null
        if (!byParent.has(key)) byParent.set(key, [])
        byParent.get(key)!.push(u)
      }
      const attach = (u: StructuralUnit): StructuralUnitNode => ({
        ...u,
        children: (byParent.get(u.id) ?? []).map(attach),
      })
      return (byParent.get(null) ?? []).map(attach)
    },
  },
  actions: {
    async ensureLoaded() {
      await latest.ensure(this, () => this.reload())
    },
    async reload() {
      await latest.run(this, {
        // listAllResource: справочники (типы устройств, здания и т.п.) должны загружаться целиком.
        // Обычно они небольшие и умещаются в одну страницу (1000 записей), но если записей
        // больше, helper дочитывает остальные страницы — иначе лишние молча пропали бы из списков.
        //
        // Promise.allSettled, а не Promise.all: 21 каталог грузится одним пакетом, и раньше
        // сбой (сетевой сбой/таймаут) ХОТЯ БЫ ОДНОГО ресурса ронял весь Promise.all — ни один из
        // 21 каталогов не записывался в items, loaded оставался false, и приложение выглядело
        // так, будто сломались вообще все лукапы (Тип/Производитель/Модель, Здание/Помещение,
        // Домен VLAN и т.д. сразу), хотя реально не смог загрузиться, например, только один
        // редко нужный каталог. allSettled записывает то, что реально пришло, а не проваленные
        // ключи перечисляет в this.error.
        fetch: () =>
          Promise.all([
            Promise.allSettled(CATALOGS.map((key) => listAllResource<CatalogItem>(key))),
            api.get<ResourceDescriptor[]>('/resources'),
            listAllResource<ProtocolPortCatalogEntry>('protocol-port-catalog'),
          ]),
        apply: ([catalogResults, resources, protocolPorts]) => {
          const failedKeys: string[] = []
          const truncatedLoads: Array<[string, AllPagesResponse<unknown>]> = []
          CATALOGS.forEach((key, i) => {
            const result = catalogResults[i]
            if (result.status === 'fulfilled') {
              this.items[key] = sortCatalogItems(key, result.value.items)
              if (result.value.truncated) truncatedLoads.push([key, result.value])
            } else {
              failedKeys.push(key)
            }
          })
          if (protocolPorts.truncated) truncatedLoads.push(['protocol-port-catalog', protocolPorts])
          this.resourceNames = Object.fromEntries(resources.map((r) => [r.key, r.name]))
          // Состояние усечения — всегда по последней загрузке: после полной перезагрузки признак снимается.
          this.incompleteCatalogs = Object.fromEntries(truncatedLoads.map(([key, res]) => [key, { loaded: res.items.length, total: res.total }]))
          for (const [key, res] of truncatedLoads) warnIfTruncated(res, `справочник «${this.resourceNames[key] ?? key}»`)
          // Фикс п.4.2 (найден при работе над "убрать текстовые поля Порт/Протокол"): раньше
          // сортировался только результат quick-add (QuickAddModal.vue), а сама начальная загрузка —
          // нет, из-за чего справочник в SearchableSelect был отсортирован только ПОСЛЕ первого
          // добавления записи через "+", а до этого — в порядке ответа бэкенда.
          this.protocolPortCatalog = sortProtocolPortCatalog(protocolPorts.items)
          this.loaded = true
          this.error = failedKeys.length ? `Не удалось загрузить справочники: ${failedKeys.join(', ')}` : null
        },
        errorMessage: 'Не удалось загрузить справочники',
      })
    },
    label(key: CatalogKey, id: string | null | undefined, fallback = '—'): string {
      if (!id) return fallback
      const item = this.indexOf(key).get(id)
      if (!item) return fallback
      if (key === 'device-models') {
        return [item.model, item.name].filter(Boolean).join(' — ') || fallback
      }
      if (key === 'operating-systems' || key === 'embedded-os') {
        return [item.name, item.version].filter(Boolean).join(' ') || fallback
      }
      return (item.name as string) ?? fallback
    },
    /** Применяет точечное изменение каталога, уже подтверждённое сервером (быстрое добавление записи, смена портов устройства).
     * reload(), начатый до изменения, принесёт снимок без него и затёр бы только что внесённую запись; его ответ отбрасывается,
     * а чтобы остальные справочники не остались устаревшими, загрузка запускается заново. */
    applyLocalChange(change: () => void): void {
      const wasLoading = latest.invalidate(this)
      change()
      if (wasLoading) void this.reload()
    },
    /** Точечно заменяет интерфейсы одного устройства в уже загруженном каталоге 'interfaces' —
     * тот же приём, что точечное добавление в QuickAddModal.vue (createResource + merge вместо
     * полного catalogs.reload()). Нужно после PUT /devices/{id}/interfaces из DevicePortsModal.vue
     * (управление портами с экрана «Подключения»): без этого экран продолжал бы показывать в
     * селектах порта устаревший список портов устройства до следующей полной перезагрузки
     * справочников. items — как есть из ответа sync_interfaces, без ?? [] у самого items (не
     * бывает undefined, PUT всегда возвращает массив), но items['interfaces'] может быть ещё не
     * загружен (форма открылась раньше catalogs.ensureLoaded()) — тогда просто ничего не покажется
     * в селекте до следующего reload(), как и в остальных точечных обновлениях каталога. */
    replaceDeviceInterfaces(deviceId: string, items: CatalogItem[]) {
      this.applyLocalChange(() => {
        const current = this.items['interfaces'] ?? []
        this.items['interfaces'] = sortCatalogItems('interfaces', [...current.filter((i) => i.physical_device_id !== deviceId), ...items])
      })
    },
    /** Точечно заменяет ОДИН порт в уже загруженном каталоге 'interfaces' — после смены его роли
     * (PUT /interfaces/{id}/port-role). В отличие от replaceDeviceInterfaces() не трогает остальные
     * порты устройства. Если каталог ещё не загружен или порта в нём нет — ничего не делает: при
     * следующей загрузке порт придёт уже с актуальными флагами. */
    replaceInterface(item: CatalogItem) {
      this.applyLocalChange(() => {
        const current = this.items['interfaces']
        if (!current || !current.some((i) => i.id === item.id)) return
        this.items['interfaces'] = sortCatalogItems(
          'interfaces',
          current.map((i) => (i.id === item.id ? item : i)),
        )
      })
    },
    /** Точечно добавляет только что созданную запись каталога (QuickAddModal.vue) в уже
     * загруженный список, сохраняя сортировку — та же причина не звать полный reload(), что и в
     * replaceDeviceInterfaces() выше, плюс фикс п.4.2: без пересортировки здесь новая запись
     * всегда падала бы в конец списка, а не туда, где ей место по алфавиту. ?? [] у current —
     * то же поведение, что было в QuickAddModal.vue раньше: даже если каталог ещё не был
     * загружен (items[key] === undefined, форма открылась раньше catalogs.ensureLoaded()),
     * созданная запись всё равно попадает в список одна, чтобы вызывающий select хотя бы мог
     * показать её как выбранную, а не молча проигнорировать value без своего <option>. */
    addCatalogItem(key: CatalogKey, item: CatalogItem) {
      this.applyLocalChange(() => {
        this.items[key] = sortCatalogItems(key, [...(this.items[key] ?? []), item])
      })
    },
    /** Точечно добавляет только что загруженную пользовательскую иконку диаграммы в уже
     * загруженный каталог 'diagram-icons' — тот же приём, что replaceDeviceInterfaces() выше,
     * без полного catalogs.reload() ради одной новой записи (см. DeviceIconPicker.vue). */
    addDiagramIcon(icon: CatalogItem) {
      this.applyLocalChange(() => {
        this.items['diagram-icons'] = [...(this.items['diagram-icons'] ?? []), icon]
      })
    },
    /** id единицы + все id её потомков — нужно для фильтра "включая дочерние" (см. reporting.py backend). */
    unitAndDescendantIds(rootId: string): Set<string> {
      const result = new Set<string>([rootId])
      const children = new Map<string, string[]>()
      for (const u of this.structuralUnits) {
        if (!u.parent_id) continue
        if (!children.has(u.parent_id)) children.set(u.parent_id, [])
        children.get(u.parent_id)!.push(u.id)
      }
      const stack = [...(children.get(rootId) ?? [])]
      while (stack.length) {
        const id = stack.pop()!
        if (result.has(id)) continue
        result.add(id)
        stack.push(...(children.get(id) ?? []))
      }
      return result
    },
  },
})
