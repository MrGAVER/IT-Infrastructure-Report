<script setup lang="ts">
// Форма покрывает собственные поля InformationSystem, а также вложенные связи — подразделения,
// протоколы, источники размещения/IP, места размещения — через отдельный атомарный ресурс
// /resources/information-systems/{id}/details (см. InformationSystemDetails в api/types.ts).
// Портировано с openInformationSystemForm/saveInformationSystemForm в
// frontend/static/information-systems.js, включая одноразовую миграцию устаревших связанных
// таблиц (ips/devices/vms/containers) в унифицированный sources при первом открытии формы для
// ИС, у которой sources ещё пуст, — иначе такая ИС выглядела бы в новом UI так, будто у неё
// вообще нет источников, хотя данные есть, просто в старых таблицах.
import { computed, reactive, ref, watch } from 'vue'
import { api, createResource, updateResource } from '../api/client'
import type {
  InformationSystem,
  InformationSystemDetails,
  ISSource,
  ISSourceDraftRow,
  ISProtocolDraftRow,
  CatalogPickerDraftRow,
} from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { useVMsStore } from '../stores/vms'
import { useContainersStore } from '../stores/containers'
import { filterHostDevices } from '../utils/deviceFilters'
import CatalogPickerListEditor from './CatalogPickerListEditor.vue'
import ISProtocolsListEditor from './ISProtocolsListEditor.vue'
import ISSourcesListEditor from './ISSourcesListEditor.vue'
import QuickAddButton from './QuickAddButton.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

const props = defineProps<{ system: InformationSystem | null }>()
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
    physical_device_id: x.physical_device_id ?? '',
    virtual_machine_id: x.virtual_machine_id ?? '',
    container_id: x.container_id ?? '',
    ip_address: x.ip_address ?? '',
    purpose: x.purpose ?? '',
    role: x.role ?? '',
    external_interaction: x.external_interaction,
  }
}

// Одноразовая миграция устаревших связанных таблиц в sources — портировано дословно с
// openInformationSystemForm() в frontend/static/information-systems.js. Срабатывает только
// когда details.sources пуст: для ИС, уже сохранённых через новый UI (или через vanilla после
// того, как он тоже перешёл на sources), sources уже заполнен и эта функция не трогается.
function migrateLegacyToSources(details: InformationSystemDetails): ISSource[] {
  if (details.sources.length) return details.sources
  const migrated: ISSource[] = []
  for (const x of details.devices) {
    migrated.push({ id: '', source_type: 'device', physical_device_id: x.physical_device_id, virtual_machine_id: null, container_id: null, ip_address: '', purpose: '', role: x.role ?? '', external_interaction: false })
  }
  for (const x of details.vms) {
    migrated.push({ id: '', source_type: 'vm', physical_device_id: null, virtual_machine_id: x.virtual_machine_id, container_id: null, ip_address: '', purpose: '', role: x.role ?? '', external_interaction: false })
  }
  for (const x of details.containers) {
    migrated.push({ id: '', source_type: 'container', physical_device_id: null, virtual_machine_id: null, container_id: x.container_id, ip_address: '', purpose: '', role: x.role ?? '', external_interaction: false })
  }
  const keyOf = (x: Pick<ISSource, 'source_type' | 'physical_device_id' | 'virtual_machine_id' | 'container_id'>) =>
    `${x.source_type}:${x.physical_device_id || x.virtual_machine_id || x.container_id || ''}`
  for (const ip of details.ips) {
    const key = ip.virtual_machine_id ? `vm:${ip.virtual_machine_id}` : ip.physical_device_id ? `device:${ip.physical_device_id}` : `manual:${ip.ip_address}`
    const existing = migrated.find((x) => keyOf(x) === key)
    if (existing) {
      existing.ip_address = existing.ip_address ? `${existing.ip_address}, ${ip.ip_address}` : ip.ip_address
      existing.purpose = ip.purpose || existing.purpose
      existing.external_interaction = Boolean(ip.external_interaction)
    } else {
      migrated.push({ id: '', source_type: 'manual', physical_device_id: null, virtual_machine_id: null, container_id: null, ip_address: ip.ip_address || '', purpose: ip.purpose ?? '', role: '', external_interaction: Boolean(ip.external_interaction) })
    }
  }
  return migrated
}

watch(
  () => props.system,
  async (s) => {
    Object.assign(form, emptyForm())
    departments.value = []
    protocols.value = []
    sources.value = []
    placementAssets.value = []
    if (s) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = s[key as keyof InformationSystem]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
    }

    loadingNested.value = true
    try {
      const [, details] = await Promise.all([
        containersStore.ensureLoaded(),
        s ? api.get<InformationSystemDetails>(`/resources/information-systems/${s.id}/details`) : Promise.resolve(null),
      ])
      if (details) {
        departments.value = details.departments.map((x) => ({ id: x.id, catalogId: x.department_id }))
        protocols.value = details.protocols.map((x) => ({ id: x.id, protocol_catalog_id: x.protocol_catalog_id ?? '', protocol: x.protocol, port: x.port, description: x.description ?? '' }))
        sources.value = migrateLegacyToSources(details).map(toSourceDraftRow)
        placementAssets.value = details.placement_assets.map((x) => ({ id: x.id, catalogId: x.placement_asset_id }))
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
// saveInformationSystemForm() в vanilla-версии: legacy-таблицы всегда пустые (вся актуальная
// информация идёт через sources), пустые строки справочников/протоколов отбрасываются, а
// source-строки отбрасываются только если тип "вручную" и IP не заполнен — для остальных типов
// строка сохраняется, даже если сам источник (сервер/ВМ/контейнер) ещё не выбран.
function buildDetailsPayload() {
  return {
    departments: departments.value.filter((x) => x.catalogId).map((x) => ({ id: x.id, department_id: x.catalogId })),
    ips: [],
    protocols: protocols.value
      .filter((x) => x.protocol_catalog_id || x.protocol.trim())
      .map((x) => ({ id: x.id, protocol_catalog_id: x.protocol_catalog_id || null, protocol: x.protocol, port: x.port, description: x.description || null })),
    devices: [],
    vms: [],
    containers: [],
    sources: sources.value
      .filter((x) => (x.source_type === 'manual' ? x.ip_address.trim() : true))
      .map((x) => ({
        id: x.id,
        source_type: x.source_type,
        physical_device_id: x.physical_device_id || null,
        virtual_machine_id: x.virtual_machine_id || null,
        container_id: x.container_id || null,
        ip_address: x.ip_address || null,
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
          <input v-model.trim="form.name" type="text" required maxlength="500" />
        </label>

        <label class="field field-wide">
          <span>Общее описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Назначение использования</span>
          <textarea v-model.trim="form.purpose" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Локализация</span>
          <textarea v-model.trim="form.localization" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field">
          <span>Организация технической поддержки</span>
          <div class="lookup-row">
            <select v-model="form.support_organization_id">
              <option value="">— не указана —</option>
              <option v-for="o in catalogs.items['support-organizations'] ?? []" :key="o.id" :value="o.id">{{ o.name }}</option>
            </select>
            <QuickAddButton resource="support-organizations" title="Организация технической поддержки" @created="(r) => (form.support_organization_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Способ оказания техподдержки</span>
          <div class="lookup-row">
            <select v-model="form.support_method_id">
              <option value="">— не указан —</option>
              <option v-for="m in catalogs.items['support-methods'] ?? []" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
            <QuickAddButton resource="support-methods" title="Способ оказания техподдержки" @created="(r) => (form.support_method_id = r.id)" />
          </div>
        </label>

        <label class="field field-wide">
          <span>Описание процесса функционирования</span>
          <textarea v-model.trim="form.process_description" rows="2" maxlength="4000"></textarea>
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
            <select v-model="form.crypto_protection_description_id" :disabled="!form.crypto_protection_enabled">
              <option value="">— не указано —</option>
              <option v-for="c in catalogs.items['crypto-protection-means'] ?? []" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
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
.lookup-row select {
  flex: 1;
  min-width: 0;
}
.field input[type='text'],
.field select,
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
.field select:disabled {
  opacity: 0.5;
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
