<script setup lang="ts">
// hypervisor_os_id НЕ отправляется пользователем — бэкенд всегда пересчитывает его
// сам из ОС выбранного физического хоста (см. backend/app/services/crud.py:
// create_resource/update_resource, VirtualMachine: "data['hypervisor_os_id'] = host.
// operating_system_id..."). Поле показано только как read-only предпросмотр того,
// что реально запишется. Хост-устройство дополнительно отфильтровано на клиенте
// до серверов/СХД (validate_vm_host в services/validation.py отклонит остальные
// типы с 422) — фильтрация здесь не замена серверной проверке, а просто не даёт
// пользователю выбрать заведомо невалидный вариант.
import { computed, reactive, ref, watch } from 'vue'
import { createResource, deleteResource, listResource, updateResource } from '../api/client'
import type { VirtualMachine, Device, VMIP, OpenPort, VMSoftware, VmIpDraftRow, OpenPortDraftRow, SoftwareAssetDraftRow } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useDevicesStore } from '../stores/devices'
import { filterHostDevices } from '../utils/deviceFilters'
import VmIpListEditor from './VmIpListEditor.vue'
import OpenPortListEditor from './OpenPortListEditor.vue'
import SoftwareAssetListEditor from './SoftwareAssetListEditor.vue'
import QuickAddButton from './QuickAddButton.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'

const props = defineProps<{ vm: VirtualMachine | null }>()
const emit = defineEmits<{ close: []; saved: [vm: VirtualMachine] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.vm !== null)

function emptyForm() {
  return {
    name: '',
    operating_system_id: '',
    physical_device_id: '',
    purpose: '',
    description: '',
  }
}
const form = reactive(emptyForm())

// Staged локально до сохранения самой ВМ — так же, как vmIpRows/vmOpenPortRows
// в vanilla-версии (frontend/static/vm-editors.js): для НОВОЙ ВМ строки можно
// заполнить сразу в той же форме, ещё до того, как у записи появится id, а
// реально отправить на сервер только после того, как известен id (см. submit()).
const vmIps = ref<VmIpDraftRow[]>([])
const openPorts = ref<OpenPortDraftRow[]>([])
const softwareAssets = ref<SoftwareAssetDraftRow[]>([])
const loadingNested = ref(false)

function toIpDraftRow(x: VMIP): VmIpDraftRow {
  return {
    id: x.id,
    ip_address: x.ip_address,
    prefix_length: x.prefix_length == null ? '' : String(x.prefix_length),
    purpose: x.purpose ?? '',
    is_management: x.is_management,
  }
}

function toOpenPortDraftRow(x: OpenPort): OpenPortDraftRow {
  return {
    id: x.id,
    protocol_catalog_id: x.protocol_catalog_id ?? '',
    port: String(x.port),
    protocol: x.protocol ?? '',
    transport_protocol: x.transport_protocol,
    description: x.description ?? '',
  }
}

function toSoftwareDraftRow(x: VMSoftware): SoftwareAssetDraftRow {
  return { id: x.id, software_asset_id: x.software_asset_id, version: x.version ?? '' }
}

watch(
  () => props.vm,
  async (vm) => {
    Object.assign(form, emptyForm())
    vmIps.value = []
    openPorts.value = []
    softwareAssets.value = []
    if (!vm) return
    form.name = vm.name
    form.operating_system_id = vm.operating_system_id ?? ''
    form.physical_device_id = vm.physical_device_id ?? ''
    form.purpose = vm.purpose ?? ''
    form.description = vm.description ?? ''

    loadingNested.value = true
    try {
      const [ips, ports, software] = await Promise.all([
        listResource<VMIP>('vm-ips', { virtual_machine_id: vm.id, limit: 1000 }),
        listResource<OpenPort>('open-ports', { owner_type: 'virtual_machine', owner_id: vm.id, limit: 1000 }),
        listResource<VMSoftware>('vm-software', { virtual_machine_id: vm.id, limit: 1000 }),
      ])
      vmIps.value = ips.items.map(toIpDraftRow)
      openPorts.value = ports.items.map(toOpenPortDraftRow)
      softwareAssets.value = software.items.map(toSoftwareDraftRow)
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить IP-адреса, открытые порты и ПО ВМ'
    } finally {
      loadingNested.value = false
    }
  },
  { immediate: true },
)

const hostCandidates = computed<Device[]>(() => filterHostDevices(devicesStore.all, catalogs))

const derivedHypervisor = computed(() => {
  if (!form.physical_device_id) return null
  const host = devicesStore.all.find((d) => d.id === form.physical_device_id)
  if (!host?.operating_system_id) return 'у хоста не указана ОС'
  return catalogs.label('operating-systems', host.operating_system_id)
})

function toPayload() {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return payload
}

// Delete-затем-recreate, а не диффинг по id — ровно тот же подход, что
// saveVMIPs()/saveVMOpenPorts() в vanilla-версии (frontend/static/vm-editors.js).
// Списки маленькие (единицы-десятки строк на ВМ), поэтому цена лишних
// запросов пренебрежимо мала по сравнению с простотой кода без diff-логики.
async function persistVmIps(vmId: string) {
  const existing = await listResource<VMIP>('vm-ips', { virtual_machine_id: vmId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('vm-ips', old.id)
  }
  for (const row of vmIps.value) {
    if (!row.ip_address.trim()) continue
    await createResource<VMIP>('vm-ips', {
      virtual_machine_id: vmId,
      ip_address: row.ip_address.trim(),
      prefix_length: row.prefix_length === '' ? null : Number(row.prefix_length),
      purpose: row.purpose || null,
      is_management: row.is_management,
    })
  }
}

async function persistOpenPorts(vmId: string) {
  const existing = await listResource<OpenPort>('open-ports', { owner_type: 'virtual_machine', owner_id: vmId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('open-ports', old.id)
  }
  for (const row of openPorts.value) {
    // port — NOT NULL на бэкенде (backend/app/models.py:OpenPort), в отличие от
    // vanilla-версии здесь не отправляем строку без порта, даже если выбрана
    // запись справочника: иначе сервер ответит 409 (нарушение целостности)
    // вместо понятной валидационной ошибки.
    if (!row.port.trim()) continue
    await createResource<OpenPort>('open-ports', {
      owner_type: 'virtual_machine',
      owner_id: vmId,
      protocol_catalog_id: row.protocol_catalog_id || null,
      port: Number(row.port),
      protocol: row.protocol || null,
      transport_protocol: row.transport_protocol || 'TCP',
      description: row.description || null,
    })
  }
}

async function persistSoftwareAssets(vmId: string) {
  const existing = await listResource<VMSoftware>('vm-software', { virtual_machine_id: vmId, limit: 1000 })
  for (const old of existing.items) {
    await deleteResource('vm-software', old.id)
  }
  for (const row of softwareAssets.value) {
    if (!row.software_asset_id) continue
    await createResource<VMSoftware>('vm-software', {
      virtual_machine_id: vmId,
      software_asset_id: row.software_asset_id,
      version: row.version || null,
    })
  }
}

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите название виртуальной машины.'
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    const saved = isEdit.value
      ? await updateResource<VirtualMachine>('vms', props.vm!.id, payload)
      : await createResource<VirtualMachine>('vms', payload)
    await persistVmIps(saved.id)
    await persistOpenPorts(saved.id)
    await persistSoftwareAssets(saved.id)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить виртуальную машину'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать виртуальную машину' : 'Добавить виртуальную машину' }}</h2>
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
          <span>Название *</span>
          <input v-model.trim="form.name" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Операционная система</span>
          <div class="lookup-row">
            <select v-model="form.operating_system_id">
              <option value="">— не указана —</option>
              <option v-for="os in catalogs.items['operating-systems'] ?? []" :key="os.id" :value="os.id">
                {{ catalogs.label('operating-systems', os.id) }}
              </option>
            </select>
            <QuickAddButton resource="operating-systems" title="Операционная система" @created="(r) => (form.operating_system_id = r.id)" />
          </div>
        </label>

        <label class="field">
          <span>Физическое устройство (хост)</span>
          <select v-model="form.physical_device_id">
            <option value="">— не указано —</option>
            <option v-for="d in hostCandidates" :key="d.id" :value="d.id">{{ d.system_name || d.serial_number }}</option>
          </select>
          <small v-if="!hostCandidates.length" class="hint-small">Нет доступных серверов/СХД в реестре устройств.</small>
        </label>

        <label class="field">
          <span>Гипервизор (определяется автоматически по хосту)</span>
          <input :value="derivedHypervisor ?? '—'" type="text" disabled />
        </label>

        <label class="field field-wide">
          <span>Целевое назначение</span>
          <textarea v-model.trim="form.purpose" rows="2" maxlength="2000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <p v-if="loadingNested" class="loading-hint field-wide">Загрузка IP-адресов и открытых портов…</p>
        <VmIpListEditor v-else v-model="vmIps" />
        <OpenPortListEditor v-if="!loadingNested" v-model="openPorts" :catalog-entries="catalogs.protocolPortCatalog" />
        <SoftwareAssetListEditor v-if="!loadingNested" v-model="softwareAssets" :catalog-entries="catalogs.items['software-assets'] ?? []" />
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
  max-width: 600px;
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
}
.field-wide {
  grid-column: 1 / -1;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
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
}
.field input:disabled {
  opacity: 0.7;
  font-style: italic;
}
.hint-small {
  color: var(--status-warn);
  font-size: 10.5px;
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
