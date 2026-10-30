<script setup lang="ts">
// Панель генератора портов: количество, «Начать нумерацию с», шаблон имени ({n} / {n0}), тип и скорость по умолчанию, галочка
// «Заменить все порты» и кнопка «Сгенерировать». Поля — черновой ввод формы (usePortGenerator), не часть списка портов: панель
// собирает их через v-model, а саму генерацию выполняет родитель по событию generate. Без галочки новые интерфейсы добавляются к
// существующим, с галочкой — существующие заменяются шаблонными значениями (после подтверждения).
import type { CatalogItem } from '../api/types'
import { TEMPLATE_HELP_TEXT } from '../utils/interfaceRowDraft'
import HelpTip from './HelpTip.vue'
import QuickAddButton from './QuickAddButton.vue'

defineProps<{
  typeOptions: CatalogItem[]
  speedOptions: CatalogItem[]
}>()
const emit = defineEmits<{
  generate: []
}>()
// Число портов хранится строкой (поле type="number" отдаёт число, пустое поле — ''), разбор — в usePortGenerator.
const count = defineModel<string>('count', { required: true })
// Пусто — «не задано» (1 при замене, продолжение от числа строк при добавлении), а не 0.
const startAt = defineModel<string>('startAt', { required: true })
const nameTemplate = defineModel<string>('nameTemplate', { required: true })
// '' — тип / скорость не заданы.
const typeId = defineModel<string>('typeId', { required: true })
const speedId = defineModel<string>('speedId', { required: true })
const replaceAll = defineModel<boolean>('replaceAll', { required: true })
</script>

<template>
  <div class="generator">
    <label>
      <span>Количество</span>
      <input type="number" min="0" v-model="count" />
    </label>
    <label>
      <span>Начать нумерацию с</span>
      <input
        type="number"
        v-model="startAt"
        placeholder="авто"
        title="Например, 'Количество: 20' и 'Начать с: 5' сгенерируют порты с номерами 5-24. Пусто — прежнее поведение: 1 при замене, продолжение от количества уже добавленных портов при дополнении."
      />
    </label>
    <label>
      <span>Шаблон имени <HelpTip :text="TEMPLATE_HELP_TEXT" /></span>
      <input type="text" v-model="nameTemplate" placeholder="eth{n}" />
    </label>
    <label>
      <span>Тип по умолчанию</span>
      <div class="lookup-row">
        <select v-model="typeId">
          <option value="">— не выбрано —</option>
          <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
        <QuickAddButton resource="interface-types" title="Тип интерфейса" @created="(r) => (typeId = r.id)" />
      </div>
    </label>
    <label>
      <span>Скорость по умолчанию</span>
      <div class="lookup-row">
        <select v-model="speedId">
          <option value="">— не выбрано —</option>
          <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <QuickAddButton resource="interface-speeds" title="Скорость интерфейса" @created="(r) => (speedId = r.id)" />
      </div>
    </label>
    <div class="generator-actions">
      <label class="replace-all-check">
        <input type="checkbox" v-model="replaceAll" />
        <span>Заменить все порты</span>
      </label>
      <button type="button" class="btn btn-secondary" @click="emit('generate')">Сгенерировать</button>
    </div>
  </div>
  <span class="hint generator-hint"
    >Без галочки «Заменить все порты» новые интерфейсы добавляются к уже существующим, не изменяя их. С галочкой — все существующие интерфейсы заменяются
    шаблонными значениями (после подтверждения).</span
  >
</template>

<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped>
.generator {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.generator label > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.generator-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.replace-all-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.replace-all-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.generator-hint {
  display: block;
  margin-top: -4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator input,
.generator select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 130px;
}
.generator .lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.generator .lookup-row select {
  width: 130px;
}
</style>
