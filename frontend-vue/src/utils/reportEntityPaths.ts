// Плоский список путей полей до 2 связей вглубь (field / relation.field / relation[].relation2.field)
// для палитры полей и подсказки рядом с полем пути ячейки. Ровно один сегмент "[]" на путь — то же
// ограничение, что и в report_engine.py:validate_path на бэкенде (не более одной связи "многие" в
// одном пути). Портировано из rbFlattenPaths()/rbLabel() прежнего vanilla-фронтенда (до 2.60.0) —
// один в один та же логика обхода, чтобы палитра предлагала ровно те пути, которые бэкенд примет.
import type { ReportEntityMeta } from '../api/types'

export interface FlatFieldPath {
  path: string
  label: string
  hops: number
  many: boolean
}

/** entitiesByKey — индекс entities по .key, строится один раз вызывающей стороной (см.
 * ReportGridEditorView.vue) и переиспользуется между вызовами flattenEntityPaths для разных строк
 * — сам индекс сюда не входит, чтобы не пересобирать его на каждый вызов. */
export function indexEntitiesByKey(entities: ReportEntityMeta[]): Record<string, ReportEntityMeta> {
  return Object.fromEntries(entities.map((e) => [e.key, e]))
}

export function entityLabel(entitiesByKey: Record<string, ReportEntityMeta>, key: string): string {
  return entitiesByKey[key]?.label ?? key
}

export function flattenEntityPaths(entitiesByKey: Record<string, ReportEntityMeta>, entityKey: string, maxHops = 2): FlatFieldPath[] {
  const out: FlatFieldPath[] = []
  const seen = new Set<string>()

  function walk(curKey: string, segs: string[], labels: string[], hops: number, manyUsed: boolean) {
    const info = entitiesByKey[curKey]
    if (!info) return
    for (const f of info.fields) {
      const path = [...segs, f.name].join('.')
      if (seen.has(path)) continue
      seen.add(path)
      out.push({ path, label: [...labels, f.label].join(' → '), hops, many: manyUsed })
    }
    if (hops >= maxHops) return
    for (const rel of info.to_one) walk(rel.target, [...segs, rel.name], [...labels, entityLabel(entitiesByKey, rel.target)], hops + 1, manyUsed)
    if (!manyUsed) {
      for (const rel of info.to_many) {
        walk(rel.target, [...segs, `${rel.name}[]`], [...labels, `${entityLabel(entitiesByKey, rel.target)} (список)`], hops + 1, true)
      }
    }
  }

  walk(entityKey, [], [], 0, false)
  return out.slice(0, 500)
}
