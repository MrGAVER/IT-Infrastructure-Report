// Стор правил автоматического согласования данных порта. Правила и порядок их проверки хранит и
// проверяет сервер (backend/app/services/port_sync_store.py); здесь — список для страницы
// «Правила согласования портов» и операции над ним. После каждой операции берётся ответ сервера, а
// не локальная догадка: сервер переписывает порядок и признак «изменено» у стандартных правил.
import { defineStore } from 'pinia'
import { createPortSyncRule, deletePortSyncRule, fetchPortSyncRules, reorderPortSyncRules, resetPortSyncRule, updatePortSyncRule } from '../api/portSync'
import type { PortSyncRule, PortSyncRuleInput } from '../api/types'
import { movedOrder } from '../utils/portSyncRules'
import { createLatestRequest } from '../utils/latestRequest'

function byPriority(rules: PortSyncRule[]): PortSyncRule[] {
  return [...rules].sort((a, b) => a.priority - b.priority || a.id.localeCompare(b.id))
}

// Ответ на более ранний запрос не должен затереть более поздний или подтверждённое изменение (см. utils/latestRequest.ts).
const latest = createLatestRequest()

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
      await latest.run(this, {
        fetch: fetchPortSyncRules,
        apply: (res) => {
          this.rules = byPriority(res.items)
          this.loaded = true
        },
        errorMessage: 'Не удалось загрузить правила',
      })
    },
    /** Принимает список, подтверждённый сервером (ответ на изменение). Загрузка, начатая до изменения, принесла бы снимок без него и
     * откатила бы его (включённое правило снова выключено, удалённое вернулось): её ответ отбрасывается, а чтобы остальные данные
     * не остались устаревшими, загрузка запускается заново. */
    applyConfirmed(rules: PortSyncRule[]): void {
      const wasLoading = latest.invalidate(this)
      this.rules = byPriority(rules)
      if (wasLoading) void this.load()
    },
    /** Заменяет правило ответом сервера (или добавляет новое) и сохраняет порядок проверки. */
    upsert(rule: PortSyncRule): PortSyncRule {
      const exists = this.rules.some((r) => r.id === rule.id)
      this.applyConfirmed(exists ? this.rules.map((r) => (r.id === rule.id ? rule : r)) : [...this.rules, rule])
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
      this.applyConfirmed(this.rules.filter((r) => r.id !== id))
    },
    /** Сдвигает правило на одну позицию в порядке проверки; сервер перенумеровывает приоритеты. */
    async move(id: string, delta: -1 | 1): Promise<void> {
      const ids = this.rules.map((r) => r.id)
      const next = movedOrder(ids, id, delta)
      if (next.every((value, index) => value === ids[index])) return
      this.applyConfirmed((await reorderPortSyncRules(next)).items)
    },
  },
})
