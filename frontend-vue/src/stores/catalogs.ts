// Стор справочников: подгружает статичные каталоги (типы устройств, производители,
// здания, помещения, структурные единицы и т.п.) один раз за сессию и резолвит
// id → отображаемое имя для колонок таблиц. Аналог CACHEABLE_LIST_RESOURCES +
// lookupLabel() в текущем vanilla-фронтенде (frontend/static/core.js), но с типами
// и явным состоянием загрузки вместо ad-hoc Map-кеша поверх fetch().
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import type { CatalogItem, StructuralUnit } from '../api/types'

/** Узел дерева структурных единиц — рекурсивно типизированный (см. StructuralUnitTree.vue). */
export interface StructuralUnitNode extends StructuralUnit {
  children: StructuralUnitNode[]
}

// Ресурсы, которые реально используются на экране "Инвентаризация устройств".
// Расширять по мере добавления новых экранов — не грузим то, что не показываем.
const CATALOGS = [
  'device-types',
  'manufacturers',
  'device-models',
  'operating-systems',
  'embedded-os',
  'buildings',
  'rooms',
  'racks',
  'structural-units',
] as const
type CatalogKey = (typeof CATALOGS)[number]

export const useCatalogsStore = defineStore('catalogs', {
  state: () => ({
    items: {} as Record<CatalogKey, CatalogItem[]>,
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    /** Быстрый лукап id → запись для конкретного каталога. */
    indexOf: (state) => {
      const cache = new Map<CatalogKey, Map<string, CatalogItem>>()
      return (key: CatalogKey): Map<string, CatalogItem> => {
        let idx = cache.get(key)
        if (!idx) {
          idx = new Map((state.items[key] ?? []).map((it) => [it.id, it]))
          cache.set(key, idx)
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
      this.loading = true
      this.error = null
      try {
        // limit=1000: справочники (типы устройств, здания и т.п.) обычно небольшие
        // и должны загружаться целиком за один запрос — тот же лимит, что кеш
        // CACHEABLE_LIST_RESOURCES в текущем vanilla-фронтенде (core.js).
        const results = await Promise.all(
          CATALOGS.map((key) => listResource<CatalogItem>(key, { limit: 1000 })),
        )
        CATALOGS.forEach((key, i) => {
          this.items[key] = results[i].items
        })
        this.loaded = true
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
