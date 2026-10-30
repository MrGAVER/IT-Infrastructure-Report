// Стор правил автоматического согласования данных порта. Правила и порядок их проверки хранит и
// проверяет сервер (backend/app/services/port_sync_store.py); здесь — список для страницы
// «Правила согласования портов» и операции над ним. После каждой операции берётся ответ сервера, а
// не локальная догадка: сервер переписывает порядок и признак «изменено» у стандартных правил.
import { defineStore } from 'pinia'
import { createPortSyncRule, deletePortSyncRule, fetchPortSyncRules, reorderPortSyncRules, resetPortSyncRule, updatePortSyncRule } from '../api/portSync'
import type { PortSyncRule, PortSyncRuleInput } from '../api/types'
import { movedOrder } from '../utils/portSyncRules'

function byPriority(rules: PortSyncRule[]): PortSyncRule[] {
  return [...rules].sort((a, b) => a.priority - b.priority || a.id.localeCompare(b.id))
}

export const usePortSyncRulesStore = defineStore('portSyncRules', {
  state: () => ({
    rules: [] as PortSyncRule[],
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    enabledCount: (state): number => state.rules.filter((r) => r.enabled).length,
    byId:
      (state) =>
      (id: string): PortSyncRule | undefined =>
        state.rules.find((r) => r.id === id),
  },
  actions: {
    async load(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        this.rules = byPriority((await fetchPortSyncRules()).items)
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить правила'
      } finally {
        this.loading = false
      }
    },
    /** Заменяет правило ответом сервера (или добавляет новое) и сохраняет порядок проверки. */
    upsert(rule: PortSyncRule): PortSyncRule {
      const exists = this.rules.some((r) => r.id === rule.id)
      this.rules = byPriority(exists ? this.rules.map((r) => (r.id === rule.id ? rule : r)) : [...this.rules, rule])
      return rule
    },
    async create(input: Partial<PortSyncRuleInput>): Promise<PortSyncRule> {
      return this.upsert(await createPortSyncRule(input as PortSyncRuleInput))
    },
    async update(id: string, patch: Partial<PortSyncRuleInput>): Promise<PortSyncRule> {
      return this.upsert(await updatePortSyncRule(id, patch))
    },
    async toggle(id: string): Promise<PortSyncRule> {
      const rule = this.byId(id)
      if (!rule) throw new Error('Правило не найдено')
      return this.update(id, { enabled: !rule.enabled })
    },
    async reset(id: string): Promise<PortSyncRule> {
      return this.upsert(await resetPortSyncRule(id))
    },
    async remove(id: string): Promise<void> {
      await deletePortSyncRule(id)
      this.rules = this.rules.filter((r) => r.id !== id)
    },
    /** Сдвигает правило на одну позицию в порядке проверки; сервер перенумеровывает приоритеты. */
    async move(id: string, delta: -1 | 1): Promise<void> {
      const ids = this.rules.map((r) => r.id)
      const next = movedOrder(ids, id, delta)
      if (next.every((value, index) => value === ids[index])) return
      this.rules = byPriority((await reorderPortSyncRules(next)).items)
    },
  },
})
