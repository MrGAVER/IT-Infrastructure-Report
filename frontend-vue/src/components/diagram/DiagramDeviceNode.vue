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

// Небольшой глиф формы в левом верхнем углу — не силуэт устройства целиком (раздел 4.3 ТЗ:
// "реальные товарные знаки/логотипы не воспроизводятся"), просто визуальное отличие категорий
// друг от друга на канвасе, тем же путём short-hand, что и в .svg-экспорте.
const SHAPE_GLYPHS: Record<string, string> = {
  server: 'M2 2h10v2H2zM2 5h10v2H2zM2 8h10v2H2z',
  switch: 'M1 4h3v4H1zM5.5 4h3v4h-3zM10 4h3v4h-3z',
  // Пункт 5 правки "диаграмма топологии сети": до этого switch_l2/switch_l3/router не
  // существовали как формы вовсе — L2- и L3-коммутаторы получали один и тот же 'switch' (три
  // порта), маршрутизатор — 'generic' (ромб) вместе с точками Wi-Fi/GSM-модемами. switch_l2 —
  // тот же символ, что и раньше был у 'switch' (три блока-порта); switch_l3 — то же самое плюс
  // маленький треугольник-стрелка сверху (символ маршрутизации поверх коммутации); router —
  // компас/крест из 4 стрелок с центром — устоявшийся в сетевых схемах символ маршрутизатора,
  // визуально не похожий ни на один из существующих значков.
  switch_l2: 'M1 4h3v4H1zM5.5 4h3v4h-3zM10 4h3v4h-3z',
  switch_l3: 'M1 5h3v4H1zM5.5 5h3v4h-3zM10 5h3v4h-3zM6 0l2.5 3.5h-5z',
  router: 'M5 4.5h2v2H5zM6 0l1.5 3h-3zM6 11l-1.5-3h3zM0 5.5l3-1.5v3zM12 5.5l-3-1.5v3z',
  firewall: 'M6 0 11 2v4c0 3.5-2.2 5.7-5 6-2.8-.3-5-2.5-5-6V2z',
  workstation: 'M1 2h12v6H1zM5 10h4v1H5z',
  peripheral: 'M6 0a5 5 0 100 10A5 5 0 006 0z',
  generic: 'M6 1 11 6 6 11 1 6z',
}

const props = defineProps<NodeProps<DiagramDeviceNodeData>>()

const icon = computed(() => props.data.icon)
const isCustom = computed(() => icon.value.mode === 'custom')
const fillColor = computed(() => (icon.value.mode === 'generated' ? icon.value.color || FALLBACK_COLOR : FALLBACK_COLOR))
const shape = computed(() => (icon.value.mode === 'generated' ? icon.value.shape : 'generic'))
const glyphPath = computed(() => SHAPE_GLYPHS[shape.value] ?? SHAPE_GLYPHS.generic)
// Засечки порта раньше рисовались только для shape === 'switch'; теперь backend считает
// port_ticks для ЛЮБОГО сгенерированного значка (см. services/diagram_icons.py), так что
// видимость завязана просто на "у устройства есть хотя бы один известный порт" — работает
// одинаково для switch, сервера с несколькими NIC, файрвола с WAN/LAN/DMZ и т.д.
const portTicks = computed(() => (icon.value.mode === 'generated' ? Math.max(0, Math.min(icon.value.port_ticks ?? 0, MAX_PORT_TICKS)) : 0))
const portOverflow = computed(() => (icon.value.mode === 'generated' ? icon.value.port_overflow ?? 0 : 0))

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
      <div class="custom-icon" v-html="sanitizedCustomSvg"></div>
    </template>
    <div v-else class="generated-icon" :style="{ background: fillColor }">
      <svg class="shape-glyph" viewBox="0 0 12 11"><path :d="glyphPath" fill="rgba(255,255,255,0.85)" /></svg>
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
  left: 6px;
  width: 14px;
  height: 13px;
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
