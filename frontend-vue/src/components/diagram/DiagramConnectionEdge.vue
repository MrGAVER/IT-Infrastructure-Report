<script setup lang="ts">
// Кастомный тип ребра диаграммы топологии (раздел 4.4 ТЗ, доп. правка: "визуально показано,
// какой порт подключён к какому — с указанием их названий"). Компонент намеренно тонкий и НЕ
// покрыт собственным mount-тестом: BaseEdge/EdgeLabelRenderer читают контекст <VueFlow> через
// inject, а подъём реального канваса в jsdom — известное ограничение (см. комментарий в начале
// utils/diagramFlow.ts). Вся содержательная логика (текст подписей, геометрия отступа) вынесена
// в чистые функции diagramFlow.ts и проверяется там; этот файл только раскладывает их результат
// по разметке.
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core'
import type { DiagramEdge } from '../../api/diagrams'
import { edgeAngleDeg, edgeMidLabel, edgeSourcePortLabel, edgeTargetPortLabel, offsetAlongHandle } from '../../utils/diagramFlow'

const props = defineProps<EdgeProps<DiagramEdge>>()

const bezier = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  }),
)
const path = computed(() => bezier.value[0])
const midX = computed(() => bezier.value[1])
const midY = computed(() => bezier.value[2])

const midLabel = computed(() => edgeMidLabel(props.data))
const sourcePortLabel = computed(() => edgeSourcePortLabel(props.data))
const targetPortLabel = computed(() => edgeTargetPortLabel(props.data))
const sourceLabelPos = computed(() => offsetAlongHandle(props.sourceX, props.sourceY, props.sourcePosition))
const targetLabelPos = computed(() => offsetAlongHandle(props.targetX, props.targetY, props.targetPosition))
// Пункт 3 правки "диаграмма топологии сети": один угол на все три подписи этого ребра, а не
// горизонтальный текст независимо от направления линии (см. edgeAngleDeg — нормализован, чтобы
// подпись никогда не оказывалась вверх ногами).
const angle = computed(() => edgeAngleDeg(props.sourceX, props.sourceY, props.targetX, props.targetY))
// Пункт 4: DiagramView.vue приглушает НЕсвязанные с наведением рёбра через props.style.opacity
// (см. edgeIsRelatedToHover) — тот style применяется только к <BaseEdge> (сама линия), подписи
// рисуются отдельно через EdgeLabelRenderer со своим style и не унаследовали бы его сами по
// себе: подпись осталась бы чёткой на фоне потускневшей линии, что выглядело бы непоследовательно.
const opacity = computed(() => {
  const raw = (props.style as Record<string, unknown> | undefined)?.opacity
  return typeof raw === 'number' ? raw : 1
})

function labelStyle(x: number, y: number) {
  return { transform: `translate(-50%, -50%) translate(${x}px, ${y}px) rotate(${angle.value}deg)`, opacity: opacity.value }
}
</script>

<template>
  <BaseEdge :id="id" :path="path" :marker-start="markerStart" :marker-end="markerEnd" :style="style" />
  <EdgeLabelRenderer>
    <div v-if="midLabel" class="diagram-edge-label diagram-edge-label--mid" :style="labelStyle(midX, midY)">
      {{ midLabel }}
    </div>
    <div v-if="sourcePortLabel" class="diagram-edge-label diagram-edge-label--port" :style="labelStyle(sourceLabelPos.x, sourceLabelPos.y)">
      {{ sourcePortLabel }}
    </div>
    <div v-if="targetPortLabel" class="diagram-edge-label diagram-edge-label--port" :style="labelStyle(targetLabelPos.x, targetLabelPos.y)">
      {{ targetPortLabel }}
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.diagram-edge-label {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  white-space: nowrap;
  font-size: 10px;
  line-height: 1.3;
  color: var(--ink, #e6edf3);
  background: var(--surface, #16212e);
  border: 1px solid var(--border, #2a3b4d);
  border-radius: var(--r-s, 4px);
  padding: 1px 5px;
}
.diagram-edge-label--mid {
  font-weight: 600;
}
.diagram-edge-label--port {
  font-size: 9px;
  color: var(--ink-muted, #8fa0b3);
}
</style>
