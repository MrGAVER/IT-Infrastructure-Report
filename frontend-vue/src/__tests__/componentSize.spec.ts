import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// «Трещотка» размера компонентов: цель ревью — не более {LIMIT} строк в .vue (логика — в composables/ и utils/, крупные части разметки —
// в дочерних компонентах). Новый или выросший компонент сверх предела тест не пропускает; уже превышающие — перечислены с текущим размером
// и только сокращаются: уменьшили файл — обновите число, уложили в предел — удалите запись (устаревшую запись тест не терпит).
const LIMIT = 400
const FROZEN_OVER_LIMIT: Record<string, number> = {
  'components/ConnectionCanvasModal.vue': 559,
  'components/DeviceInterfacesEditor.vue': 541,
  'components/InformationSystemFormModal.vue': 507,
  'components/DeviceVlanListEditor.vue': 527,
  'components/DeviceStackFormModal.vue': 524,
  'views/VLANsView.vue': 517,
  'views/DiagramView.vue': 487,
  'views/DevicesView.vue': 474,
  'components/VMFormModal.vue': 453,
  'views/ReportDocxEditorView.vue': 466,
  'components/PortConfigReviewModal.vue': 459,
  'components/InterfaceConnectionEditor.vue': 434,
  'components/DeviceStackVlanIpEditor.vue': 431,
  'components/SearchableSelect.vue': 429,
  'views/OtherCatalogsView.vue': 426,
}

const SRC = join(__dirname, '..')

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : vueFiles(path)
    return name.endsWith('.vue') ? [path] : []
  })
}

function lineCount(path: string): number {
  return readFileSync(path, 'utf-8').split('\n').length - 1
}

const sizes = new Map(vueFiles(SRC).map((path) => [relative(SRC, path).split('\\').join('/'), lineCount(path)]))

describe('размер компонентов', () => {
  it('ни один компонент не длиннее предела, кроме перечисленных, и перечисленные не растут', () => {
    const violations = [...sizes]
      .filter(([, lines]) => lines > LIMIT)
      .filter(([file, lines]) => !(file in FROZEN_OVER_LIMIT) || lines > FROZEN_OVER_LIMIT[file])
      .map(([file, lines]) => `${file}: ${lines} строк (предел ${LIMIT}, записано ${FROZEN_OVER_LIMIT[file] ?? '—'})`)
    expect(violations).toEqual([])
  })

  it('в списке нет устаревших записей: файл удалён или уже укладывается в предел', () => {
    const stale = Object.keys(FROZEN_OVER_LIMIT).filter((file) => !((sizes.get(file) ?? 0) > LIMIT))
    expect(stale).toEqual([])
  })

  it('пять компонентов из ревью уложены в предел', () => {
    for (const file of [
      'views/ReportGridEditorView.vue',
      'components/InterfaceSubinterfacesEditor.vue',
      'views/ConnectionsView.vue',
      'components/PortConfigEditModal.vue',
      'views/DeviceStacksView.vue',
    ]) {
      expect(sizes.get(file), file).toBeLessThanOrEqual(LIMIT)
    }
  })
})
