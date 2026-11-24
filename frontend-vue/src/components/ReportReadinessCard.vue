<script setup lang="ts">
// «Готовность отчёта» на дашборде: по каждому листу Excel-отчёта — какая доля объектов не имеет проблем, требующих внимания.
// Числа считает сервер (backend/app/services/consistency/readiness.py) по тем же находкам, что и экран «Проверка данных»;
// отсюда ссылки ведут на этот экран сразу с нужным листом. Данные не меняются.
import { onMounted, ref } from 'vue'
import { fetchReportReadiness } from '../api/consistency'
import type { ReportReadiness, SheetReadiness } from '../api/consistency'
import { pluralRu } from '../utils/plural'

const readiness = ref<ReportReadiness | null>(null)
const loading = ref(true)
const errorText = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    readiness.value = await fetchReportReadiness()
  } catch (err) {
    // Блок без данных не должен выглядеть как «отчёт готов»: показываем причину и даём повторить.
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const problemsLabel = (n: number) => `${n} ${pluralRu(n, ['проблема', 'проблемы', 'проблем'])}`
const sheetLink = (sheet: SheetReadiness) => ({ path: '/consistency', query: { sheet: String(sheet.sheet) } })
const isDone = (sheet: SheetReadiness) => sheet.checked && sheet.total > 0 && sheet.affected === 0
</script>

<template>
  <section class="readiness card" aria-labelledby="readiness-title">
    <header class="head">
      <h2 id="readiness-title">Готовность отчёта</h2>
      <router-link to="/consistency" class="all-link">Открыть проверку данных</router-link>
    </header>

    <div v-if="errorText" class="error" role="alert">
      <span>Не удалось посчитать готовность: {{ errorText }}</span>
      <button type="button" class="btn btn-secondary" :disabled="loading" @click="load">Повторить</button>
    </div>
    <div v-else-if="!readiness" class="loading">Считаем готовность…</div>
    <template v-else>
      <ul class="sheets">
        <li v-for="sheet in readiness.sheets" :key="sheet.sheet" class="sheet" :data-sheet="sheet.sheet">
          <div class="sheet-head">
            <span class="sheet-title">Лист {{ sheet.sheet }} — {{ sheet.title }}</span>
            <span v-if="sheet.percent !== null" class="percent" :class="{ done: isDone(sheet) }">{{ sheet.percent }} %</span>
          </div>

          <template v-if="!sheet.checked">
            <p class="muted">Проверки для этого листа пока не реализованы. Подключений в реестре: {{ sheet.total }}.</p>
          </template>
          <p v-else-if="sheet.total === 0" class="muted">На листе пока нет объектов.</p>
          <template v-else>
            <div
              class="bar"
              role="progressbar"
              :aria-label="`Готовность листа ${sheet.sheet}`"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="sheet.percent ?? 0"
            >
              <span class="fill" :class="{ done: isDone(sheet) }" :style="{ width: `${sheet.percent ?? 0}%` }"></span>
            </div>
            <p class="meta">
              <template v-if="isDone(sheet)">Все объекты готовы ({{ sheet.total }})</template>
              <template v-else>
                Готовы {{ sheet.ready }} из {{ sheet.total }} · {{ problemsLabel(sheet.problems) }}
                <router-link :to="sheetLink(sheet)" class="show-link">Показать</router-link>
              </template>
              <template v-if="sheet.approved > 0"> · одобрено: {{ sheet.approved }}</template>
            </p>
            <p v-if="sheet.top_rules.length" class="muted top-rules">
              Чаще всего: {{ sheet.top_rules.map((item) => `${item.title} (${item.count})`).join('; ') }}
            </p>
          </template>
        </li>
      </ul>
      <p v-if="readiness.unassigned > 0" class="unassigned">
        Ещё {{ problemsLabel(readiness.unassigned) }} не привязаны к листу (например, повтор IP-адреса) и задевают несколько листов.
        <router-link to="/consistency">Открыть</router-link>
      </p>
    </template>
  </section>
</template>

<style scoped>
.readiness {
  margin-top: 16px;
  padding: 16px 18px;
}
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.head h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.all-link,
.show-link,
.unassigned a {
  color: var(--brand-ink);
  font-size: 12px;
}
.sheets {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 24px;
}
.sheet-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 6px;
}
.sheet-title {
  font-size: 13px;
  font-weight: 600;
}
.percent {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}
.percent.done {
  color: var(--status-ok);
}
.bar {
  height: 8px;
  border-radius: 4px;
  background: var(--surface-2);
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  background: var(--brand);
  border-radius: 4px;
}
.fill.done {
  background: var(--status-ok);
}
.meta,
.muted,
.unassigned {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}
.top-rules {
  margin-top: 2px;
}
.unassigned {
  margin-top: 14px;
}
.error {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--status-crit);
  font-size: 13px;
}
.loading {
  color: var(--ink-muted);
  font-size: 13px;
}
@media (max-width: 760px) {
  .sheets {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
