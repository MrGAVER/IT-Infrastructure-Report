<script setup lang="ts">
// Фикс п.3.4 (батч4): "проработать визуальный режим подключения устройств с выводом устройств и
// их портов и выполнению подключений через соединение их курсором мыши". Это ДОБАВКА к
// стандартному ConnectionFormModal.vue (устройство -> устройство по одному), а не замена — сама
// схема служит быстрым, наглядным способом ВЫБРАТЬ пару "порт источника / порт назначения", а
// оформление подключения (тип линии связи, назначение, статус, выравнивание расхождений
// is_management/is_data_transfer) целиком отдаётся уже существующей, протестированной форме через
// новый необязательный проп prefill (см. её комментарий) — не дублируем эту логику здесь.
//
// Геометрия узла на схеме считается чисто по layout-формулам (позиция устройства + индекс порта
// в списке его интерфейсов), а не измерением DOM через getBoundingClientRect() на каждый порт —
// это делает координаты пинов детерминированными, дешёвыми для computed() и не требующими
// перерасчёта после каждого рендера.
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { Connection, Device, DeviceInterface } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { sortOptionsByLabel } from '../utils/selectOptions'
import { useDevicesStore } from '../stores/devices'
import { useConnectionsStore } from '../stores/connections'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useToast } from '../composables/useToast'
import SearchableSelect from './SearchableSelect.vue'
import ConnectionFormModal from './ConnectionFormModal.vue'

const emit = defineEmits<{ close: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const connectionsStore = useConnectionsStore()
const { notify, notifyError } = useToast()

// Геометрия карточки устройства на схеме — подобраны на глаз под компактный список портов.
const NODE_WIDTH = 220
const HEADER_HEIGHT = 34
const PORT_ROW_HEIGHT = 32
// Фикс "линии от центра блока к центру блока -> от точки к точке портов": раньше pinPosition()
// координатой X всегда брал NODE_WIDTH/2 (горизонтальный центр ВСЕЙ карточки) — линии сходились
// в одну вертикальную ось внутри блока, а не в реальные точки-кружки (.port-pin) у каждого
// порта. Теперь pinPosition() указывает ровно на центр .port-pin — эти два смещения должны
// держаться в синхроне с CSS .port-row/.port-pin-row/.port-pin ниже (см. комментарий в её CSS,
// почему координаты не измеряются через DOM, а держатся отдельными константами).
const PIN_CENTER_X = 15 // padding-left (10) + половина ширины .port-pin (10/2)
// PORT_ROW теперь двухстрочная (см. фикс "название порта должно быть над линией" ниже): сверху
// узкая строка с названием порта, снизу — сам pin. PIN_CENTER_Y — расстояние от верха строки
// порта до центра pin'а: 4 (padding-top) + 12 (высота строки названия) + 16/2 (половина высоты
// строки pin'а) = 24.
const PIN_CENTER_Y = 24
const NODE_GAP_X = 60
const NODE_GAP_Y = 40
const GRID_COLS = 3
const CANVAS_MARGIN = 60

function deviceLabel(d: Device): string {
  return d.system_name || d.serial_number
}
function deviceById(id: string): Device | undefined {
  return devicesStore.all.find((d) => d.id === id)
}

const allInterfaces = computed(() => (catalogs.items['interfaces'] ?? []) as unknown as DeviceInterface[])
function interfacesOf(deviceId: string): DeviceInterface[] {
  return allInterfaces.value.filter((i) => i.physical_device_id === deviceId)
}
function isOccupied(interfaceId: string): boolean {
  return connectionsStore.occupiedInterfaceIds.has(interfaceId)
}

// --- Устройства, добавленные на схему (только в рамках текущего открытия — не персистится:
// схема нужна как рабочий стол для сборки подключений, а не как ещё одно хранимое представление
// топологии) ---
const canvasDeviceIds = ref<string[]>([])
const positions = reactive<Record<string, { x: number; y: number }>>({})
const addDeviceId = ref('')

const availableDeviceOptions = computed(() =>
  sortOptionsByLabel(devicesStore.all.filter((d) => !canvasDeviceIds.value.includes(d.id)).map((d) => ({ value: d.id, label: deviceLabel(d) }))),
)

function nextGridPosition(): { x: number; y: number } {
  const index = canvasDeviceIds.value.length
  const col = index % GRID_COLS
  const row = Math.floor(index / GRID_COLS)
  return { x: CANVAS_MARGIN + col * (NODE_WIDTH + NODE_GAP_X), y: CANVAS_MARGIN + row * (220 + NODE_GAP_Y) }
}

function addDevice() {
  if (!addDeviceId.value || canvasDeviceIds.value.includes(addDeviceId.value)) return
  canvasDeviceIds.value = [...canvasDeviceIds.value, addDeviceId.value]
  positions[addDeviceId.value] = nextGridPosition()
  addDeviceId.value = ''
}
function removeDevice(deviceId: string) {
  canvasDeviceIds.value = canvasDeviceIds.value.filter((id) => id !== deviceId)
  delete positions[deviceId]
}

function nodeHeight(deviceId: string): number {
  return HEADER_HEIGHT + Math.max(1, interfacesOf(deviceId).length) * PORT_ROW_HEIGHT + 12
}

const canvasSize = computed(() => {
  let width = 700
  let height = 420
  for (const deviceId of canvasDeviceIds.value) {
    const pos = positions[deviceId]
    if (!pos) continue
    width = Math.max(width, pos.x + NODE_WIDTH + CANVAS_MARGIN)
    height = Math.max(height, pos.y + nodeHeight(deviceId) + CANVAS_MARGIN)
  }
  return { width, height }
})

// --- Перетаскивание карточки устройства по схеме (за заголовок — сами строки портов должны
// оставаться доступны для запуска протяжки соединения, см. ниже) ---
const canvasEl = ref<HTMLElement | null>(null)
const draggingNode = ref<{ deviceId: string; offsetX: number; offsetY: number } | null>(null)

// Фикс: .canvas-area — сам по себе скроллящийся контейнер (overflow:auto, см. его CSS), а
// карточки/pin'ы внутри позиционируются position:absolute в его СОДЕРЖИМОМ (canvas-координаты),
// а не в его видимой области. getBoundingClientRect() даёт позицию ВИДИМОЙ области контейнера в
// вьюпорте — без прибавления scrollLeft/scrollTop координата курсора считалась бы так, будто
// прокрутки не было вовсе: чем больше проскроллено вниз, тем сильнее конец протягиваемой линии
// отстаёт от курсора вверх (сам баг). Прокрутка СТРАНИЦЫ (.overlay, overflow-y:auto) сюда не
// относится — getBoundingClientRect() уже сама пересчитывается при любой прокрутке страницы, в
// отличие от прокрутки СОДЕРЖИМОГО самого canvasEl.
// null — холста уже нет в DOM (модалку закрыли посреди перетаскивания): координаты считать не из чего.
function canvasPoint(event: MouseEvent): { x: number; y: number } | null {
  const el = canvasEl.value
  if (!el) return null
  const rect = el.getBoundingClientRect()
  return { x: event.clientX - rect.left + el.scrollLeft, y: event.clientY - rect.top + el.scrollTop }
}

function onNodeHeaderMouseDown(deviceId: string, event: MouseEvent) {
  const point = canvasPoint(event)
  if (!point) return
  const pos = positions[deviceId]
  draggingNode.value = { deviceId, offsetX: point.x - pos.x, offsetY: point.y - pos.y }
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
}

function onWindowMouseMove(event: MouseEvent) {
  const point = canvasPoint(event)
  if (!point) return
  if (draggingNode.value) {
    const { deviceId, offsetX, offsetY } = draggingNode.value
    positions[deviceId] = { x: Math.max(0, point.x - offsetX), y: Math.max(0, point.y - offsetY) }
  } else if (connectDrag.value) {
    connectDrag.value = { ...connectDrag.value, x: point.x, y: point.y }
  }
}

function onWindowMouseUp(event: MouseEvent) {
  if (draggingNode.value) draggingNode.value = null
  if (connectDrag.value) finishConnectDrag(event)
  detachWindowDragListeners()
}

/** Слушатели вешаются на window на время перетаскивания (иначе движение за пределами холста терялось бы) и
 * обязаны сниматься всегда: не только по отпусканию кнопки, но и при закрытии модалки посреди перетаскивания
 * (Esc, клик по оверлею, смена маршрута) или если mouseup пришёлся вне окна браузера. */
function detachWindowDragListeners() {
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
}
onBeforeUnmount(() => {
  detachWindowDragListeners()
  draggingNode.value = null
  connectDrag.value = null
})

// --- Протягивание соединения курсором мыши от порта к порту ---
const connectDrag = ref<{ sourceInterfaceId: string; x: number; y: number } | null>(null)

function onPinMouseDown(interfaceId: string, event: MouseEvent) {
  event.stopPropagation() // иначе всплыло бы до .node-header и запустило бы перетаскивание узла
  if (isOccupied(interfaceId)) return
  const point = canvasPoint(event)
  if (!point) return
  connectDrag.value = { sourceInterfaceId: interfaceId, x: point.x, y: point.y }
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
}

/** Порт-получатель определяется через elementFromPoint в точке отпускания кнопки мыши (а не
 * через @mouseup на самом элементе порта) — во время протяжки курсор перемещается свободно над
 * ЛЮБЫМИ элементами схемы, не обязательно теми, что запустили перетаскивание, и native mouseup
 * должен сработать именно там, где отпущена кнопка, а не там, где было нажатие. */
function findInterfaceIdAtPoint(clientX: number, clientY: number): string | null {
  const el = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>('[data-interface-id]')
  return el?.dataset.interfaceId ?? null
}

const pendingConnection = ref<{ sourceInterfaceId: string; destinationInterfaceId: string } | null>(null)

function finishConnectDrag(event: MouseEvent) {
  const drag = connectDrag.value
  connectDrag.value = null
  if (!drag) return
  const targetInterfaceId = findInterfaceIdAtPoint(event.clientX, event.clientY)
  if (!targetInterfaceId || targetInterfaceId === drag.sourceInterfaceId) return
  if (isOccupied(targetInterfaceId)) {
    notify('Этот порт уже занят активным подключением.', 'error')
    return
  }
  pendingConnection.value = { sourceInterfaceId: drag.sourceInterfaceId, destinationInterfaceId: targetInterfaceId }
}

function closePendingConnection() {
  pendingConnection.value = null
}
async function onConnectionCreated() {
  pendingConnection.value = null
  try {
    await connectionsStore.reload()
    notify('Подключение добавлено', 'success')
  } catch (err) {
    notifyError(err)
  }
}

// --- Редактирование существующего подключения по клику на линию ---
const editingConnection = ref<Connection | null>(null)
function openConnectionLine(c: Connection) {
  editingConnection.value = c
}
function closeEditingConnection() {
  editingConnection.value = null
}
async function onConnectionUpdated() {
  editingConnection.value = null
  try {
    await connectionsStore.reload()
    notify('Подключение обновлено', 'success')
  } catch (err) {
    notifyError(err)
  }
}

// --- Координаты пинов и линии подключений (только между устройствами, УЖЕ добавленными на
// схему — подключения к устройствам "за кадром" схема не показывает, чтобы не тянуть линии в
// никуда: она про то, что видно прямо сейчас) ---
function pinPosition(interfaceId: string): { x: number; y: number } | null {
  const iface = allInterfaces.value.find((i) => i.id === interfaceId)
  if (!iface || !canvasDeviceIds.value.includes(iface.physical_device_id)) return null
  const pos = positions[iface.physical_device_id]
  if (!pos) return null
  const ports = interfacesOf(iface.physical_device_id)
  const index = ports.findIndex((p) => p.id === interfaceId)
  if (index === -1) return null
  return { x: pos.x + PIN_CENTER_X, y: pos.y + HEADER_HEIGHT + index * PORT_ROW_HEIGHT + PIN_CENTER_Y }
}

function bezierPath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const dx = Math.max(60, Math.abs(b.x - a.x) / 2)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}

const connectionLines = computed(() =>
  connectionsStore.all
    .map((c) => {
      const a = pinPosition(c.source_interface_id)
      const b = pinPosition(c.destination_interface_id)
      if (!a || !b) return null
      return { id: c.id, path: bezierPath(a, b), active: c.is_active, connection: c }
    })
    .filter((x): x is { id: string; path: string; active: boolean; connection: Connection } => x !== null),
)

const dragLinePath = computed(() => {
  if (!connectDrag.value) return null
  const a = pinPosition(connectDrag.value.sourceInterfaceId)
  if (!a) return null
  return bezierPath(a, { x: connectDrag.value.x, y: connectDrag.value.y })
})
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card canvas-modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>Визуальный режим подключений</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div class="canvas-toolbar">
        <SearchableSelect v-model="addDeviceId" :options="availableDeviceOptions" placeholder="Добавить устройство на схему…" />
        <button type="button" class="btn btn-secondary" :disabled="!addDeviceId" @click="addDevice">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Добавить
        </button>
        <p class="hint-small canvas-hint">Перетащите точку у порта на порт другого устройства, чтобы создать подключение.</p>
      </div>

      <div ref="canvasEl" class="canvas-area">
        <p v-if="!canvasDeviceIds.length" class="canvas-empty">Добавьте на схему хотя бы два устройства, чтобы соединить их порты курсором мыши.</p>
        <template v-else>
          <div
            v-for="deviceId in canvasDeviceIds"
            :key="deviceId"
            class="device-node"
            :style="{ left: positions[deviceId].x + 'px', top: positions[deviceId].y + 'px', width: NODE_WIDTH + 'px' }"
          >
            <div class="node-header" @mousedown="onNodeHeaderMouseDown(deviceId, $event)">
              <span class="node-title" :title="deviceById(deviceId) ? deviceLabel(deviceById(deviceId)!) : ''">{{
                deviceById(deviceId) ? deviceLabel(deviceById(deviceId)!) : '—'
              }}</span>
              <button type="button" class="node-remove" aria-label="Убрать устройство со схемы" @click="removeDevice(deviceId)">
                <svg class="icon"><use href="/icons.svg#i-x" /></svg>
              </button>
            </div>
            <div v-if="!interfacesOf(deviceId).length" class="node-empty">Нет портов</div>
            <div
              v-for="iface in interfacesOf(deviceId)"
              :key="iface.id"
              class="port-row"
              :class="{ occupied: isOccupied(iface.id) }"
              :data-interface-id="iface.id"
            >
              <span class="port-name" :title="iface.name">{{ iface.name }}</span>
              <span class="port-pin-row">
                <span
                  class="port-pin"
                  :title="isOccupied(iface.id) ? 'Порт уже занят активным подключением' : 'Перетащите на другой порт, чтобы подключить'"
                  @mousedown="onPinMouseDown(iface.id, $event)"
                ></span>
              </span>
            </div>
          </div>

          <!-- SVG со связями рисуется ПОСЛЕ карточек устройств: конец линии (pinPosition()) лежит
               внутри прямоугольника карточки (у центра, на высоте строки порта), а не на его
               границе, поэтому если бы svg красился раньше, эта часть каждой линии пропадала бы
               под непрозрачным фоном .device-node (баг — "линии под блоками устройств"). Клики по
               самим карточкам/пинам это не задевает: pointer-events:none стоит на всём <svg>,
               кроме собственно линий (pointer-events:stroke). -->
          <svg class="canvas-svg" :width="canvasSize.width" :height="canvasSize.height" :viewBox="`0 0 ${canvasSize.width} ${canvasSize.height}`">
            <path
              v-for="line in connectionLines"
              :key="line.id"
              :d="line.path"
              class="connection-line"
              :class="{ inactive: !line.active }"
              @click="openConnectionLine(line.connection)"
            />
            <path v-if="dragLinePath" :d="dragLinePath" class="connection-line drag-preview" />
          </svg>
        </template>
      </div>
    </div>

    <ConnectionFormModal
      v-if="pendingConnection"
      :connection="null"
      :prefill="pendingConnection"
      @close="closePendingConnection"
      @saved="onConnectionCreated"
    />
    <ConnectionFormModal v-if="editingConnection" :connection="editingConnection" @close="closeEditingConnection" @saved="onConnectionUpdated" />
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 30px 16px;
  overflow-y: auto;
}
.canvas-modal {
  width: 100%;
  max-width: 1180px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.canvas-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.canvas-toolbar .searchable-select {
  min-width: 240px;
}
.canvas-hint {
  margin: 0 0 0 auto;
  color: var(--ink-muted);
}
.canvas-area {
  position: relative;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  background: var(--surface-2);
  min-height: 60vh;
  max-height: 65vh;
  overflow: auto;
}
.canvas-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-muted);
  font-size: 13px;
  padding: 20px;
  text-align: center;
}
.canvas-svg {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 2; /* поверх .device-node — см. комментарий в шаблоне про порядок в DOM */
  pointer-events: none; /* клики проваливаются на карточки узлов, кроме самих линий ниже */
}
.connection-line {
  fill: none;
  stroke: var(--brand);
  stroke-width: 2;
  pointer-events: stroke; /* сама линия кликабельна (редактирование), пустая часть svg — нет */
  cursor: pointer;
}
.connection-line.inactive {
  stroke: var(--ink-muted);
  stroke-dasharray: 5 4;
}
.connection-line.drag-preview {
  stroke: var(--status-warn);
  stroke-dasharray: 4 3;
  cursor: default;
  pointer-events: none;
}
.device-node {
  position: absolute;
  z-index: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  box-shadow: var(--shadow-s, 0 2px 8px rgba(0, 0, 0, 0.1));
  overflow: hidden;
  user-select: none;
}
.node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0 6px 0 10px;
  height: 34px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  cursor: grab;
}
.node-header:active {
  cursor: grabbing;
}
.node-title {
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.node-remove {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: none;
  border: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.node-remove:hover {
  color: var(--status-crit);
  background: var(--surface);
}
.node-remove .icon {
  width: 12px;
  height: 12px;
}
.node-empty {
  padding: 8px 10px;
  font-size: 11px;
  color: var(--ink-muted);
  height: 32px;
  display: flex;
  align-items: center;
}
/* Фикс "название порта должно быть над линией": раньше .port-pin и .port-name были соседями в
   одной строке flex-row с align-items:center — оба сидели на одной высоте, ровно там, где
   pinPosition() рисует конец линии (см. её комментарий), из-за чего линия визуально протыкала
   текст названия порта. Теперь строка порта двухстрочная: сверху узкая строка названия, снизу —
   pin (у него теперь СВОЯ подстрока .port-pin-row) — линия по-прежнему упирается ровно в pin, но
   тот сместился ниже подписи, а не делит с ней одну ось. PIN_CENTER_X/PIN_CENTER_Y в <script> —
   те же самые отступы, что и здесь (10px padding, 12px строка названия, 16px строка pin'а) —
   меняя один, обязательно поменяйте и другой. */
.port-row {
  display: flex;
  flex-direction: column;
  padding: 4px 10px 0;
  height: 32px;
  border-top: 1px solid var(--border);
}
.port-row.occupied {
  color: var(--ink-muted);
}
.port-name {
  height: 12px;
  line-height: 12px;
  font-size: 9.5px;
  color: var(--ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-mono);
}
.port-pin-row {
  display: flex;
  align-items: center;
  height: 16px;
}
.port-pin {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--brand);
  border: 2px solid var(--surface);
  outline: 1px solid var(--brand);
  cursor: crosshair;
}
.port-row.occupied .port-pin {
  background: var(--ink-muted);
  outline-color: var(--ink-muted);
  cursor: not-allowed;
}
</style>
