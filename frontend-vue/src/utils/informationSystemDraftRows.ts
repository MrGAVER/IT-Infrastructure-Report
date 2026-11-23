// Строки черновика источников информационной системы (InformationSystemFormModal.vue): ответ API → поля формы.
import type { ISSource, ISSourceDraftRow } from '../api/types'

export function toSourceDraftRow(x: ISSource): ISSourceDraftRow {
  return {
    id: x.id || undefined,
    source_type: (x.source_type as ISSourceDraftRow['source_type']) || 'manual',
    owner_id: x.owner_id ?? '',
    // Пусто: ВМ (если это source_type='vm') уже сохранена, её хост показывается через vmOptions
    // по owner_id (см. deviceSelectValue в ISSourcesListEditor.vue) — hint нужен только для ещё не
    // сохранённого выбора.
    vmHostHint: '',
    ips: x.ips.map((ip) => ({ id: ip.id, ip_address: ip.ip_address })),
    purpose: x.purpose ?? '',
    role: x.role ?? '',
    external_interaction: x.external_interaction,
  }
}
