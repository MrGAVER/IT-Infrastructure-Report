<script setup lang="ts">
import { useThemeStore, COLOR_SCHEMES } from '../stores/theme'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })
const theme = useThemeStore()
</script>

<template>
  <div class="scheme-picker" :class="{ compact }">
    <button
      v-for="s in COLOR_SCHEMES"
      :key="s.id"
      type="button"
      class="swatch-btn"
      :class="{ active: theme.schemeId === s.id }"
      :title="s.name"
      :aria-pressed="theme.schemeId === s.id"
      @click="theme.setScheme(s.id)"
    >
      <span class="swatch" :style="{ background: s.brand }">
        <svg v-if="theme.schemeId === s.id" class="icon"><use href="/icons.svg#i-check" /></svg>
      </span>
      <span v-if="!compact" class="swatch-name">{{ s.name }}</span>
    </button>
  </div>
</template>

<style scoped>
.scheme-picker {
  display: flex;
  gap: 8px;
}
.scheme-picker.compact {
  gap: 6px;
}
.swatch-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  background: none;
  border: none;
  padding: 3px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--r-s);
}
.swatch-btn:hover {
  background: var(--surface-2);
}
.swatch {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #05161c;
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.15);
  flex-shrink: 0;
}
.swatch-btn.active .swatch-name {
  color: var(--ink);
}
.swatch .icon {
  width: 12px;
  height: 12px;
}
</style>
