// Стор справочников: подгружает статичные каталоги (типы устройств, производители,
// здания, помещения, структурные единицы и т.п.) один раз за сессию и резолвит
// id → отображаемое имя для колонок таблиц. Аналог CACHEABLE_LIST_RESOURCES +
// lookupLabel() в текущем vanilla-фронтенде (frontend/static/core.js), но с типами
// и явным состоянием загрузки вместо ad-hoc Map-кеша поверх fetch().
import { defineStore } from 'pinia'
import { listResource, api } from '../api/client'
import type { CatalogItem, StructuralUnit, ResourceDescriptor, ProtocolPortCatalogEntry } from '../api/types'

// Сортировка кириллицы регистронезависимо + numeric:true — числа внутри строки сравниваются как
// числа, а не посимвольно ("Gi1/0/2" раньше "Gi1/0/19", а не наоборот, как было бы при обычном
// лексикографическом сравнении — фикс п.3.5 "натуральная сортировка" портов). Тот же collator
// годится и для обычных кириллических названий (буквы/цифры в имени организации и т.п.).
const RU_COLLATOR = new Intl.Collator('ru', { sensitivity: 'base', numeric: true })

/** Узел дерева структурных единиц — рекурсивно типизированный (см. StructuralUnitTree.vue). */
export interface StructuralUnitNode extends StructuralUnit {
  children: StructuralUnitNode[]
}

// Ресурсы, которые реально используются на экране "Инвентаризация устройств".
// Расширять по мере добавления новых экранов — не грузим то, что не показываем.
const CATALOGS = [
  'organizations',
  'device-types',
  'manufacturers',
  'device-models',
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
    return [...items].sort(
      (a, b) => RU_COLLATOR.compare(a.name, b.name) || RU_COLLATOR.compare(String(a.version ?? ''), String(b.version ?? '')),
    )
  }
  if (key === 'device-models') {
    return [...items].sort((a, b) => RU_COLLATOR.compare(String(a.model ?? ''), String(b.model ?? '')))
  }
  return [...items].sort((a, b) => RU_COLLATOR.compare(a.name, b.name))
}

export const useCatalogsStore = defineStore('catalogs', {
  state: () => ({
    items: {} as Record<CatalogKey, CatalogItem[]>,
    resourceNames: {} as Record<string, string>,
    // Отдельно от items/CATALOGS: у ProtocolPortCatalogEntry нет поля name, поэтому
    // он не подходит под общий Record<CatalogKey, CatalogItem[]> (см. комментарий
    // к типу в api/types.ts). Используется в OpenPortListEditor.vue.
    protocolPortCatalog: [] as ProtocolPortCatalogEntry[],
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    /** Человекочитаемое имя ресурса (DISPLAY_NAMES на бэкенде) — для entity_type в
     * журнале аудита. Не хардкодим словарь во фронтенде — грузим с /api/v1/resources,
     * чтобы не расходиться с бэкендом при добавлении новых ресурсов. */
    resourceLabel: (state) => (key: string): string => state.resourceNames[key] ?? key,
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
      if (this.loaded || this.loading) return
      await this.reload()
    },
    async reload() {
      this.loading = true
      this.error = null
      try {
        // limit=1000: справочники (типы устройств, здания и т.п.) обычно небольшие
        // и должны загружаться целиком за один запрос — тот же лимит, что кеш
        // CACHEABLE_LIST_RESOURCES в текущем vanilla-фронтенде (core.js).
        //
        // Promise.allSettled, а не Promise.all: 21 каталог грузится одним пакетом, и раньше
        // сбой (сетевой сбой/таймаут) ХОТЯ БЫ ОДНОГО ресурса ронял весь Promise.all — ни один из
        // 21 каталогов не записывался в items, loaded оставался false, и приложение выглядело
        // так, будто сломались вообще все лукапы (Тип/Производитель/Модель, Здание/Помещение,
        // Домен VLAN и т.д. сразу), хотя реально не смог загрузиться, например, только один
        // редко нужный каталог. allSettled записывает то, что реально пришло, а не проваленные
        // ключи перечисляет в this.error.
        const [catalogResults, resources, protocolPorts] = await Promise.all([
          Promise.allSettled(CATALOGS.map((key) => listResource<CatalogItem>(key, { limit: 1000 }))),
          api.get<ResourceDescriptor[]>('/resources'),
          listResource<ProtocolPortCatalogEntry>('protocol-port-catalog', { limit: 1000 }),
        ])
        const failedKeys: string[] = []
        CATALOGS.forEach((key, i) => {
          const result = catalogResults[i]
          if (result.status === 'fulfilled') {
            this.items[key] = sortCatalogItems(key, result.value.items)
          } else {
            failedKeys.push(key)
          }
        })
        this.resourceNames = Object.fromEntries(resources.map((r) => [r.key, r.name]))
        this.protocolPortCatalog = protocolPorts.items
        this.loaded = true
        this.error = failedKeys.length ? `Не удалось загрузить справочники: ${failedKeys.join(', ')}` : null
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить справочники'
      } finally {
        this.loading = false
      }
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
      const current = this.items['interfaces'] ?? []
      this.items['interfaces'] = sortCatalogItems('interfaces', [...current.filter((i) => i.physical_device_id !== deviceId), ...items])
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
      this.items[key] = sortCatalogItems(key, [...(this.items[key] ?? []), item])
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
