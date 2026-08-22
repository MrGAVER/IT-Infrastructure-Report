<script setup lang="ts">
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { useThemeStore, COLOR_SCHEMES } from '../stores/theme'

const theme = useThemeStore()
</script>

<template>
  <div class="settings-view">
    <section class="card section">
      <h2>Цветовая схема</h2>
      <p class="hint">
        Приложение — рабочий инструмент дежурного инженера («Диспетчерская»), поэтому фон и
        поверхности остаются тёмными во всех схемах. Меняется только фирменный акцент — цвета
        статусов (норма / внимание / тревога) не зависят от выбора и остаются узнаваемыми.
      </p>
      <ThemeSwitcher />
      <p class="current">Сейчас выбрано: <strong>{{ theme.scheme.name }}</strong></p>
    </section>

    <section class="card section preview">
      <h2>Предпросмотр</h2>
      <div class="preview-row">
        <button class="btn btn-primary">Основная кнопка</button>
        <button class="btn btn-secondary">Второстепенная кнопка</button>
        <span class="status on"><span class="status-dot"></span>SIEM: норма</span>
        <span class="status off"><span class="status-dot"></span>SIEM: внимание</span>
      </div>
      <div class="swatches">
        <div v-for="s in COLOR_SCHEMES" :key="s.id" class="swatch-row">
          <span class="dot" :style="{ background: s.brand }"></span>
          {{ s.name }} — <span class="mono">{{ s.brand }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 640px;
}
.section {
  padding: 20px 22px;
}
.section h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0 0 10px;
}
.hint {
  font-size: 12.5px;
  color: var(--ink-muted);
  line-height: 1.6;
  margin: 0 0 16px;
}
.current {
  font-size: 12.5px;
  color: var(--ink-muted);
  margin-top: 14px;
}
.preview-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.swatches {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.swatch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
