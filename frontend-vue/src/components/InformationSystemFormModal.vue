<script setup lang="ts">
// Форма покрывает собственные поля InformationSystem, а также вложенные связи — подразделения,
// протоколы, источники размещения/IP, места размещения — через отдельный атомарный ресурс
// /resources/information-systems/{id}/details (см. InformationSystemDetails в api/types.ts).
// Портировано с openInformationSystemForm/saveInformationSystemForm в
// frontend/static/information-systems.js. Устаревшие связанные таблицы (ips/devices/vms/
// containers) удалены вместе со всей их поддержкой (миграция b7f2c1e5a904, см. models.py) —
// sources (InformationSystemSource) теперь единственный источник этих данных.
import { computed, reactive, ref, watch } from 'vue'
import { api, createResource, updateResource } from '../api/client'
import type {
  InformationSystem,
  InformationSystemDetails,
  ISSource,
  ISSourceDraftRow,
  ISProtocolDraftRow,
  CatalogPickerDraftRow,
  CatalogItem,
} from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'
import { useContainersStore } from '../stores/containers'
import { filterHostDevices } from '../utils/deviceFilters'
import { isValidIPv4 } from '../utils/ipValidation'
import CatalogPickerListEditor from './CatalogPickerListEditor.vue'
import ISProtocolsListEditor from './ISProtocolsListEditor.vue'
import ISSourcesListEditor from './ISSourcesListEditor.vue'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { stripIds } from '../utils/copyEntity'
import { duplicatePortNumbers, sortOpenPortRows } from '../utils/openPorts'

const props = defineProps<{ system: InformationSystem | null; copyFrom?: InformationSystem | null }>()
const emit = defineEmits<{ close: []; saved: [system: InformationSystem] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const vmsStore = useVMsStore()
// Контейнеры теперь читаются из общего стора (см. ContainersView.vue), а не грузятся заново
// здесь при каждом открытии формы — тот же приём, что уже используется для devicesStore/
// vmsStore: форма читает уже загруженный родительским view стор, а не грузит сама
// (InformationSystemsView.vue вызывает containersStore.ensureLoaded() в onMounted).
const containersStore = useContainersStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.system !== null)

const deviceOptions = computed(() => filterHostDevices(devicesStore.all, catalogs))

const supportOrganizationOptions = computed<SearchableSelectOption[]>(() =>
  (catalogs.items['support-organizations'] ?? []).map((o) => ({ value: o.id, label: o.name })),
)

const cryptoProtectionOptions = computed<SearchableSelectOption[]>(() =>
  (catalogs.items['crypto-protection-means'] ?? []).map((c) => ({ value: c.id, label: c.name as string })),
)

/** SupportMethod.support_organization_id (models.py), если задан. CatalogItem типизирован через
 * индексную сигнатуру ([key: string]: unknown), поэтому нужен явный каст. */
function methodOrganizationId(m: CatalogItem): string | null {
  return (m.support_organization_id as string | null | undefined) ?? null
}

// Способ оказания техподдержки либо универсален (без организации — виден при любом выборе
// организации выше), либо привязан к конкретной организации (виден, только если она совпадает
// с уже выбранной у ИС — или пока организация вообще не выбрана, чтобы можно было выбрать
// способ раньше организации, а не только после). Группировка (SearchableSelectOption.group)
// отделяет организационные способы от универсальных прямо в списке. Бэкенд повторно проверяет
// эту же пару при сохранении (validate_support_method_organization в
// services/validation.py) — фильтр в форме не единственная защита от несовместимой пары.
const supportMethodOptions = computed<SearchableSelectOption[]>(() =>
  (catalogs.items['support-methods'] ?? [])
    .filter((m) => {
      const orgId = methodOrganizationId(m)
      return !orgId || !form.support_organization_id || orgId === form.support_organization_id
    })
    .map((m) => {
      const orgId = methodOrganizationId(m)
      return {
        value: m.id,
        label: m.name as string,
        group: orgId ? catalogs.label('support-organizations', orgId) : undefined,
      }
    }),
)

// Сброс выбранного способа при РУЧНОЙ смене организации (не при программной загрузке формы —
// см. вызов из шаблона через @update:model-value, а не через watch(): SearchableSelect эмитит
// update:model-value только в ответ на реальное действие пользователя, программное
// присваивание form.support_organization_id при открытии формы на редактирование через этот
// обработчик не проходит). Если этого не сделать, можно было бы отправить на сохранение
// несовместимую пару, которую бэкенд всё равно отклонит 422-й — лучше сразу очистить поле.
function onSupportOrganizationChange(orgId: string) {
  form.support_organization_id = orgId
  const method = (catalogs.items['support-methods'] ?? []).find((m) => m.id === form.support_method_id)
  if (method && methodOrganizationId(method) && methodOrganizationId(method) !== orgId) {
    form.support_method_id = ''
  }
}

function emptyForm() {
  return {
    name: '',
    description: '',
    purpose: '',
    localization: '',
    support_organization_id: '',
    support_method_id: '',
    process_description: '',
    crypto_protection_enabled: false,
    crypto_protection_description_id: '',
    siem_enabled: false,
  }
}

const form = reactive(emptyForm())

const departments = ref<CatalogPickerDraftRow[]>([])
const protocols = ref<ISProtocolDraftRow[]>([])
const sources = ref<ISSourceDraftRow[]>([])
const placementAssets = ref<CatalogPickerDraftRow[]>([])
const loadingNested = ref(false)

function toSourceDraftRow(x: ISSource): ISSourceDraftRow {
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

watch(
  () => props.system ?? props.copyFrom ?? null,
  async (source) => {
    // Аудит fix/usability-batch4 (находка №5): см. подробный комментарий в DeviceFormModal.vue.
    if (props.system && props.copyFrom) {
      console.warn('InformationSystemFormModal: одновременно переданы system и copyFrom — используется system (режим редактирования)')
    }
    const isCopy = !props.system && !!props.copyFrom
    Object.assign(form, emptyForm())
    departments.value = []
    protocols.value = []
    sources.value = []
    placementAssets.value = []
    if (source) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = source[key as keyof InformationSystem]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
      // name уникален (UniqueConstraint в backend/app/models.py) — под тем же названием копию
      // не сохранить, заставляем ввести новое явно.
      if (isCopy) form.name = ''
    }

    loadingNested.value = true
    try {
      const [, details] = await Promise.all([
        containersStore.ensureLoaded(),
        source ? api.get<InformationSystemDetails>(`/resources/information-systems/${source.id}/details`) : Promise.resolve(null),
      ])
      if (details) {
        const rawDepartments = details.departments.map((x) => ({ id: x.id, catalogId: x.department_id }))
        const rawProtocols = details.protocols.map((x) => ({ id: x.id, protocol_catalog_id: x.protocol_catalog_id, description: x.description ?? '' }))
        const rawSources = details.sources.map(toSourceDraftRow)
        const rawPlacementAssets = details.placement_assets.map((x) => ({ id: x.id, catalogId: x.placement_asset_id }))
        // При копировании каждая вложенная строка должна создаться заново под НОВОЙ ИС, а не
        // обновить запись донора — см. подробный комментарий у stripIds() выше. stripIds() сама
        // по себе НЕ рекурсивна (см. utils/copyEntity.ts) — для sources этого недостаточно: у
        // каждой строки source есть свой вложенный список ips (миграция d8e35a1c7f60), и donor'ские
        // id внутри него нужно снять отдельным проходом, иначе backend отклонит их 422 "IP не
        // принадлежит выбранному источнику" (у новой source-строки таких id ещё не может быть).
        departments.value = isCopy ? stripIds(rawDepartments) : rawDepartments
        // Протоколы — те же открытые порты, что у ВМ: форма открывается с портами по возрастанию номера
        // (сервер тоже отдаёт их так, но порядок гарантирует и эта сортировка, как в VMFormModal.vue).
        const sortedProtocols = sortOpenPortRows(rawProtocols, catalogs.protocolPortCatalog)
        protocols.value = isCopy ? stripIds(sortedProtocols) : sortedProtocols
        sources.value = isCopy ? stripIds(rawSources).map((s) => ({ ...s, ips: stripIds(s.ips) })) : rawSources
        placementAssets.value = isCopy ? stripIds(rawPlacementAssets) : rawPlacementAssets
      }
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить связанные данные информационной системы'
    } finally {
      loadingNested.value = false
    }
  },
  { immediate: true },
)

function toPayload() {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return payload
}

// Собирает payload для PUT .../details — та же фильтрация "что не отправлять", что в
// saveInformationSystemForm() в vanilla-версии: пустые строки справочников/протоколов
// отбрасываются, а source-строки отбрасываются только если тип "вручную" и IP не заполнен — для
// остальных типов строка сохраняется, даже если сам источник (сервер/ВМ/контейнер) ещё не выбран.
function buildDetailsPayload() {
  return {
    departments: departments.value.filter((x) => x.catalogId).map((x) => ({ id: x.id, department_id: x.catalogId })),
    protocols: protocols.value
      .filter((x) => x.protocol_catalog_id)
      .map((x) => ({ id: x.id, protocol_catalog_id: x.protocol_catalog_id, description: x.description || null })),
    sources: sources.value
      .filter((x) => (x.source_type === 'manual' ? x.ips.some((ip) => ip.ip_address.trim()) : true))
      .map((x) => ({
        id: x.id,
        source_type: x.source_type,
        // vmHostHint сюда намеренно не попадает — это чисто клиентское UX-состояние выбора ВМ по
        // хосту (см. api/types.ts), backend про него не знает.
        owner_id: x.owner_id || null,
        ips: x.ips.filter((ip) => ip.ip_address.trim()).map((ip) => ({ id: ip.id, ip_address: ip.ip_address.trim() })),
        purpose: x.purpose || null,
        role: x.role || null,
        external_interaction: x.external_interaction,
      })),
    placement_assets: placementAssets.value.filter((x) => x.catalogId).map((x) => ({ id: x.id, placement_asset_id: x.catalogId })),
  }
}

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование информационной системы.'
    return
  }
  // Фикс п.3: "применить исправление [валидации IP] ко всем полям с ip" — источники ИС
  // (ISSourcesListEditor.vue) тоже содержат IP-адреса, только без отдельного поля префикса.
  // Каждый источник теперь может иметь несколько отдельных полей IP (миграция d8e35a1c7f60).
  for (const row of sources.value) {
    for (const ip of row.ips) {
      if (ip.ip_address.trim() && !isValidIPv4(ip.ip_address)) {
        errorMessage.value = `Некорректный IP-адрес «${ip.ip_address}» в источниках информационной системы.`
        return
      }
    }
  }
  // Номера открытых портов (протоколов) одной ИС не повторяются — то же правило, что в форме ВМ и на
  // сервере (backend/app/services/validation.py:validate_unique_open_port_numbers).
  const duplicatePorts = duplicatePortNumbers(protocols.value, catalogs.protocolPortCatalog)
  if (duplicatePorts.length) {
    errorMessage.value = `Номера открытых портов не должны повторяться: ${duplicatePorts.join(', ')}.`
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    const saved = isEdit.value
      ? await updateResource<InformationSystem>('information-systems', props.system!.id, payload)
      : await createResource<InformationSystem>('information-systems', payload)
    await api.put(`/resources/information-systems/${saved.id}/details`, buildDetailsPayload())
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить информационную систему'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать информационную систему' : 'Добавить информационную систему' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form class="form-grid" @submit.prevent="submit">
        <label class="field field-wide">
          <span>Наименование *</span>
          <input v-model.trim="form.name" v-truncate-tooltip="form.name" type="text" required maxlength="500" />
        </label>

        <label class="field field-wide">
          <span>Общее описание</span>
          <textarea v-model.trim="form.description" v-truncate-tooltip="form.description" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Назначение использования</span>
          <textarea v-model.trim="form.purpose" v-truncate-tooltip="form.purpose" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Локализация</span>
          <textarea v-model.trim="form.localization" v-truncate-tooltip="form.localization" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field">
          <span>Организация технической поддержки</span>
          <div class="lookup-row">
            <SearchableSelect
              :model-value="form.support_organization_id"
              :options="supportOrganizationOptions"
              placeholder="— не указана —"
              @update:model-value="onSupportOrganizationChange"
            />
            <QuickAddButton resource="support-organizations" title="Организация технической поддержки" @created="(r) => (form.support_organization_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Способ оказания техподдержки</span>
          <div class="lookup-row">
            <SearchableSelect v-model="form.support_method_id" :options="supportMethodOptions" placeholder="— не указан —" />
            <QuickAddButton resource="support-methods" title="Способ оказания техподдержки" @created="(r) => (form.support_method_id = r.id)" />
          </div>
        </label>

        <label class="field field-wide">
          <span>Описание процесса функционирования</span>
          <textarea v-model.trim="form.process_description" v-truncate-tooltip="form.process_description" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.siem_enabled" type="checkbox" />
          <span>Отправляет события в SIEM</span>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.crypto_protection_enabled" type="checkbox" />
          <span>Применяются сертифицированные СКЗИ</span>
        </label>

        <label class="field field-wide">
          <span>Средство криптографической защиты</span>
          <div class="lookup-row">
            <SearchableSelect
              v-model="form.crypto_protection_description_id"
              :options="cryptoProtectionOptions"
              placeholder="— не указано —"
              :disabled="!form.crypto_protection_enabled"
            />
            <QuickAddButton
              resource="crypto-protection-means"
              title="Средство криптографической защиты"
              @created="(r) => (form.crypto_protection_description_id = r.id)"
            />
          </div>
        </label>

        <p v-if="loadingNested" class="loading-hint field-wide">Загрузка связанных данных…</p>
        <template v-else>
          <CatalogPickerListEditor
            v-model="departments"
            title="Работники, группы работников или подразделения, использующие ИС"
            placeholder="— выберите подразделение —"
            add-label="Подразделение"
            quick-add-resource="departments"
            :catalog-entries="catalogs.items['departments'] ?? []"
          />
          <ISProtocolsListEditor v-model="protocols" :catalog-entries="catalogs.protocolPortCatalog" />
          <ISSourcesListEditor v-model="sources" :device-options="deviceOptions" :vm-options="vmsStore.all" :container-options="containersStore.all" />
          <CatalogPickerListEditor
            v-model="placementAssets"
            title="Оборудование, ПО, интерфейс, на которых размещается ИС"
            placeholder="— выберите —"
            add-label="Оборудование / ПО / интерфейс"
            quick-add-resource="placement-assets"
            :catalog-entries="catalogs.items['placement-assets'] ?? []"
          />
        </template>
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>
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
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  /* п.7.2: та же правка ширины, что и в DeviceFormModal.vue (п.1.3) — форма ИС
     тоже длиннее большинства модалок (протоколы, источники размещения, места
     размещения). Обоснование clamp() — см. комментарий там же. */
  max-width: clamp(640px, 50vw, 1100px);
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.loading-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
  /* п.7.1: без min-width:0 ячейка CSS-грида не сжимается ниже intrinsic-ширины
     содержимого — длинный текст в input/textarea распирал ячейку шире грид-трека
     и вылезал за пределы подложки модалки. Тот же фикс, что в DeviceFormModal.vue
     (п.3.2 из 2.53.1). */
  min-width: 0;
}
.field-wide {
  grid-column: 1 / -1;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
/* SearchableSelect — div-обёртка, а не <select>: без flex:1 она в flex-строке сжимается до
   ширины содержимого и поле не занимает отведённую ему половину строки (организация/способ
   техподдержки) или всю ширину модалки (СКЗИ). Тот же приём, что в DeviceFormModal.vue. */
.lookup-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.field input[type='text'],
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12.5px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
