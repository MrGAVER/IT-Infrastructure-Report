<script setup lang="ts">
// Компонент узла-устройства на канвасе диаграммы топологии сети (раздел 11 ТЗ, задача 3 Агента
// B: "компонент узла по дескриптору иконки"). Та же геометрия (форма/цвет/засечки портов/
// подписи), что и бэкендовые экспортёры (backend/app/services/diagram_export.py) — единый
// визуальный словарь, разные языки реализации по разные стороны API (раздел 11 ТЗ).
import { computed } from 'vue'
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import type { DiagramDeviceNode as DiagramDeviceNodeData } from '../../api/diagrams'
import { sanitizeSvg } from '../../utils/sanitizeSvg'

// backend/app/services/diagram_icons.py:MAX_PORT_TICKS — интерфейсы за этим пределом всё ещё
// существуют (см. port_overflow), но отдельной засечки/Handle для них не рисуется.
const MAX_PORT_TICKS = 32
const NODE_WIDTH = 160
// Пункт 6 правки "диаграмма топологии сети": +14px под новую строку "серийный номер · IP"
// (см. identityLabel ниже) — раньше высота узла умещала только имя + под-подпись
// производитель/модель, серийник и IP были видны только в панели деталей по клику
// (DiagramDetailPanel.vue), а не прямо на самом значке.
const NODE_HEIGHT = 84
const FALLBACK_COLOR = '#8FA0B3'

// Иконка категории по центру верхней части узла — не силуэт устройства целиком (раздел 4.3 ТЗ:
// "реальные товарные знаки/логотипы не воспроизводятся"), а обобщённый отраслевой символ типа
// устройства. Путь глифа приходит с бэкенда в дескрипторе иконки (icon.glyph, см.
// services/diagram_icons.py:SHAPE_GLYPHS) — единственный источник правды и для канваса, и для
// .svg/.drawio-экспорта. Фаза 3, п.5 плана доработок экспорта диаграмм: раньше это был мелкий
// угловой акцент (14x13, один <path>, виден только Vue-биндингом атрибута — не через v-html, так
// как строка `d` не может содержать исполняемый код сама по себе); теперь — полноценная
// узнаваемая иконка (32x32), а glyph — фрагмент разметки из нескольких элементов (rect/circle/
// path), который нужно вставлять как реальные SVG-элементы, а не как значение одного атрибута.
// GENERIC_GLYPH — на случай кэшированного/устаревшего ответа API без поля glyph (тот же ромб,
// что и SHAPE_GLYPHS["generic"] на бэкенде).
const GENERIC_GLYPH = '<path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="1.6"/>'

const props = defineProps<NodeProps<DiagramDeviceNodeData>>()

const icon = computed(() => props.data.icon)
const isCustom = computed(() => icon.value.mode === 'custom')
const fillColor = computed(() => (icon.value.mode === 'generated' ? icon.value.color || FALLBACK_COLOR : FALLBACK_COLOR))
// v-html на самом <svg>/<g>-элементе ненадёжен кросс-браузерно (innerHTML не всегда парсит
// вставляемый фрагмент в SVG-namespace, если сам элемент-приёмник не является корневым <svg> —
// известный нюанс, из-за которого голый path/rect без обёртки может отрисоваться неправильно в
// части браузеров). Оборачиваем фрагмент в полноценный <svg> здесь же, тем же приёмом, что и
// sanitizedCustomSvg ниже (div + v-html + свой корневой <svg> внутри строки) — это гарантированно
// работает везде, а не полагается на то, что <g>, в который вставляется innerHTML, уже находится
// в SVG-контексте на момент вставки.
const glyphMarkup = computed(() => {
  const raw = (icon.value.mode === 'generated' ? icon.value.glyph : undefined) || GENERIC_GLYPH
  return sanitizeSvg(`<svg viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">${raw}</g></svg>`)
})
// Засечки порта раньше рисовались только для shape === 'switch'; теперь backend считает
// port_ticks для ЛЮБОГО сгенерированного значка (см. services/diagram_icons.py), так что
// видимость завязана просто на "у устройства есть хотя бы один известный порт" — работает
// одинаково для switch, сервера с несколькими NIC, файрвола с WAN/LAN/DMZ и т.д.
const portTicks = computed(() => (icon.value.mode === 'generated' ? Math.max(0, Math.min(icon.value.port_ticks ?? 0, MAX_PORT_TICKS)) : 0))
const portOverflow = computed(() => (icon.value.mode === 'generated' ? (icon.value.port_overflow ?? 0) : 0))

/** x-координата i-й засечки вдоль нижнего края — тот же расчёт, что
 * backend/app/services/diagram_export.py:_svg_port_ticks (spacing = width / (ticks + 1)). */
function tickX(index: number): number {
  const spacing = NODE_WIDTH / (portTicks.value + 1)
  return spacing * (index + 1)
}

const subLabel = computed(() => {
  if (icon.value.mode !== 'generated') return ''
  return [icon.value.manufacturer_label, icon.value.model_label].filter(Boolean).join(' ')
})

/** Пункт 6 правки "диаграмма топологии сети": серийный номер и основной IP прямо на значке
 * (раньше были видны только в панели деталей по клику — DiagramDetailPanel.vue). IP выбирается
 * так же, как и everywhere else в проекте, где нужен ОДИН показательный адрес из списка:
 * management-адрес в приоритете, иначе первый в списке. Совмещены в одну строку (а не две) —
 * узел и так уже вырос на одну строку под это (см. NODE_HEIGHT выше), раздувать его дальше
 * под каждое поле отдельной строкой не хотелось. */
const primaryIp = computed(() => {
  const ips = props.data.ip_addresses
  if (!ips.length) return ''
  return (ips.find((ip) => ip.is_management) ?? ips[0]).address
})
const identityLabel = computed(() => [props.data.serial_number, primaryIp.value].filter(Boolean).join(' · '))

// Код-ревью п.3.1: DiagramIcon.svg_markup — пользовательский ввод, отрисовывается через v-html.
// Санитизация — второй, независимый от бэкенда рубеж защиты (см. utils/sanitizeSvg.ts).
const sanitizedCustomSvg = computed(() => (icon.value.mode === 'custom' ? sanitizeSvg(icon.value.svg_markup) : ''))
</script>

<template>
  <div class="diagram-device-node" :class="{ selected: props.selected }" :style="{ width: `${NODE_WIDTH}px`, height: `${NODE_HEIGHT}px` }">
    <Handle v-if="portTicks === 0" type="target" :position="Position.Top" />
    <Handle v-if="portTicks === 0" type="source" :position="Position.Bottom" />

    <template v-if="isCustom && icon.mode === 'custom'">
      <!-- eslint-disable-next-line vue/no-v-html -- sanitizedCustomSvg проходит через sanitizeSvg() (utils/sanitizeSvg.ts) -->
      <div class="custom-icon" v-html="sanitizedCustomSvg"></div>
    </template>
    <div v-else class="generated-icon" :style="{ background: fillColor }">
      <!-- eslint-disable-next-line vue/no-v-html -- glyphMarkup собран из glyph иконки и проходит через sanitizeSvg() -->
      <div class="shape-glyph" v-html="glyphMarkup"></div>
    </div>

    <div class="labels">
      <div class="label" :title="data.label">{{ data.label }}</div>
      <div v-if="subLabel" class="sub-label" :title="subLabel">{{ subLabel }}</div>
      <div v-if="identityLabel" class="identity-label" :title="identityLabel">{{ identityLabel }}</div>
    </div>

    <div v-if="portTicks > 0" class="port-ticks">
      <template v-for="i in portTicks" :key="i - 1">
        <div class="port-tick" :style="{ left: `${tickX(i - 1)}px` }"></div>
        <Handle :id="`port-${i - 1}-source`" type="source" :position="Position.Bottom" :style="{ left: `${tickX(i - 1)}px` }" />
        <Handle :id="`port-${i - 1}-target`" type="target" :position="Position.Bottom" :style="{ left: `${tickX(i - 1)}px` }" />
      </template>
      <span v-if="portOverflow" class="port-overflow">+{{ portOverflow }}</span>
    </div>
  </div>
</template>

<style scoped>
.diagram-device-node {
  position: relative;
  border-radius: var(--r-m, 10px);
  border: 1.5px solid var(--border, #2a3b4d);
  background: var(--surface, #16212e);
  overflow: visible;
  cursor: grab;
}
.diagram-device-node.selected {
  border-color: var(--brand, #33c9a7);
  box-shadow: 0 0 0 2px var(--brand-soft, rgba(51, 201, 167, 0.3));
}
.generated-icon {
  position: absolute;
  inset: 0;
  border-radius: var(--r-m, 10px);
}
.custom-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: var(--r-m, 10px);
  background: var(--surface-2, #1e2c3b);
}
.custom-icon :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}
.shape-glyph {
  position: absolute;
  top: 6px;
  left: 50%;
  transform: translateX(-50%);
  width: 32px;
  height: 32px;
}
.shape-glyph :deep(svg) {
  width: 100%;
  height: 100%;
}
.labels {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding: 4px 8px 6px;
  pointer-events: none;
}
.label {
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-label {
  font-size: 9px;
  color: rgba(255, 255, 255, 0.75);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.identity-label {
  font-size: 8.5px;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: rgba(255, 255, 255, 0.6);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.port-ticks {
  position: absolute;
  bottom: -3px;
  left: 0;
  right: 0;
  height: 6px;
}
.port-tick {
  position: absolute;
  bottom: 0;
  width: 4px;
  height: 6px;
  margin-left: -2px;
  background: #222;
  border-radius: 1px;
}
.port-overflow {
  position: absolute;
  right: -6px;
  bottom: -14px;
  font-size: 9px;
  font-weight: 700;
  color: var(--ink-muted, #8fa0b3);
}
:deep(.vue-flow__handle) {
  width: 6px;
  height: 6px;
  background: transparent;
  border: none;
  opacity: 0;
}
</style>
