<script setup lang="ts">
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
defineProps<{ title: string; crumb: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()
</script>

<template>
  <div class="topbar">
    <button class="hamburger" aria-label="Меню" @click="$emit('toggle-sidebar')">
      <svg class="icon"><use href="/icons.svg#i-menu" /></svg>
    </button>
    <div class="titles">
      <div class="crumb">{{ crumb }}</div>
      <div class="page-title">{{ title }}</div>
    </div>
    <div class="topbar-right">
      <slot name="right" />
      <ThemeSwitcher compact />
      <div class="user-chip">
        <div class="avatar">АЛ</div>
        <div class="who"><b>Андрей Л.</b><span>Администратор</span></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.hamburger {
  display: none;
  background: none;
  border: none;
  color: var(--ink);
  padding: 4px;
}
.hamburger .icon {
  width: 20px;
  height: 20px;
}
.crumb {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.page-title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 19px;
  margin-top: 2px;
}
.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 16px;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 12px;
  border-left: 1px solid var(--border);
}
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--brand);
  color: #05161c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.who {
  font-size: 11.5px;
  line-height: 1.3;
}
.who b {
  display: block;
  font-size: 12px;
}
.who span {
  color: var(--ink-muted);
}

@media (max-width: 760px) {
  .hamburger {
    display: block;
  }
  .who {
    display: none;
  }
}
</style>
