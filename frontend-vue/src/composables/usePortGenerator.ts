// Генератор портов по шаблону имени (DeviceInterfacesEditor.vue): количество, шаблон, тип и скорость по умолчанию.
// Поля генератора — черновой ввод формы, не часть modelValue.
import { ref } from 'vue'
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'
import { clearReferencesTo, generateNewRows, replaceWithGenerated, resolveStartNumber, type GeneratorSettings } from '../utils/interfaceRowDraft'
import type { RowUiState } from './useRowUiState'

export interface PortGeneratorDeps {
  rows: () => InterfaceDraftRow[]
  setRows: (rows: InterfaceDraftRow[]) => void
  knownVlans: () => readonly VLANDefinition[]
  emptyRow: () => InterfaceDraftRow
}

export function usePortGenerator(deps: PortGeneratorDeps, ui: RowUiState) {
  // Начальное количество подставляется от уже загруженных интерфейсов один раз при монтировании — компонент монтируется уже
  // после загрузки данных (DeviceFormModal.vue: loadingNested), так что на этот момент список в актуальном состоянии.
  const genCount = ref(String(deps.rows().length))
  const genNameTemplate = ref('eth{n}')
  const genTypeId = ref('')
  const genSpeedId = ref('')
  // Фикс п.1.3.3: явное «Начать нумерацию с» переопределяет умолчание (1 при замене, продолжение от числа строк при
  // добавлении); пустое поле — «не задано», а не 0.
  const genStartAt = ref('')
  // Фикс п.1.3.4: одна кнопка + галочка, выключенная по умолчанию — безопасный режим (дополнить) остаётся действием по
  // умолчанию, а разрушительный (заменить) требует осознанного действия и подтверждения, если есть что терять.
  const replaceAllPorts = ref(false)

  function settings(count: number, defaultStart: number): GeneratorSettings {
    return {
      count,
      startNumber: resolveStartNumber(genStartAt.value, defaultStart),
      nameTemplate: genNameTemplate.value,
      typeId: genTypeId.value,
      speedId: genSpeedId.value,
    }
  }

  const requestedCount = () => Math.max(0, Number(genCount.value) || 0)

  // Режим «Заменить все порты»: существующие строки по индексу сохраняются (с их id/IP/VLAN), см. replaceWithGenerated.
  function generate() {
    const count = requestedCount()
    const existing = deps.rows()
    // Количество 0 при «Заменить все порты» молча удалило бы все порты — об этом предупреждаем отдельно (аудит usability-batch4, №1).
    if (existing.length > 0) {
      const message =
        count === 0
          ? `Количество для генерации равно 0 — все ${existing.length} уже добавленных порта(ов) будут удалены, новые созданы не будут. Продолжить?`
          : `Это полностью заменит все порты устройства (${existing.length} шт.) новыми, сгенерированными по шаблону. Продолжить?`
      if (!confirm(message)) return
    }
    const rows = replaceWithGenerated(existing, settings(count, 1), deps.knownVlans(), deps.emptyRow)
    ui.resetStructure()
    deps.setRows(clearReferencesTo(rows, existing.slice(count)))
    replaceAllPorts.value = false // одноразовая осознанная галочка — не должна оставаться взведённой «на будущее»
  }

  // п.1.4.1: добавляет genCount НОВЫХ интерфейсов, не трогая существующие; нумерация продолжается от числа строк. Подтверждение не нужно.
  function appendGenerated() {
    const count = requestedCount()
    if (!count) return
    const existing = deps.rows()
    const newRows = generateNewRows(settings(count, existing.length + 1), deps.emptyRow)
    ui.clearSelection()
    deps.setRows([...existing, ...newRows])
  }

  /** Единственный обработчик кнопки «Сгенерировать»: режим по галочке «Заменить все порты». */
  function applyGenerator() {
    if (replaceAllPorts.value) generate()
    else appendGenerated()
  }

  return { genCount, genStartAt, genNameTemplate, genTypeId, genSpeedId, replaceAllPorts, applyGenerator }
}
