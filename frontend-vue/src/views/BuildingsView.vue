<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useCatalogsStore } from '../stores/catalogs'
import { useAuthStore } from '../stores/auth'
import { deleteResource } from '../api/client'
import { useToast } from '../composables/useToast'
import type { Building, Room, Rack } from '../api/types'
import BuildingFormModal from '../components/BuildingFormModal.vue'
import RoomFormModal from '../components/RoomFormModal.vue'
import RackFormModal from '../components/RackFormModal.vue'
import DataLoadNotice from '../components/DataLoadNotice.vue'

const catalogs = useCatalogsStore()
const auth = useAuthStore()
const { notify, notifyError } = useToast()

onMounted(() => catalogs.ensureLoaded())

// B-02: экран показывает здания, помещения и стойки целиком из стора справочников; если какой-то из них загружен не целиком
// (потолок listAllResource), это видно постоянным сообщением, а не только исчезающим предупреждением.
const INCOMPLETE_CATALOGS = [
  { key: 'buildings', what: 'зданий' },
  { key: 'rooms', what: 'помещений' },
  { key: 'racks', what: 'стоек' },
] as const
const incompleteNotices = computed(() =>
  INCOMPLETE_CATALOGS.flatMap(({ key, what }) => {
    const info = catalogs.incompleteCatalogs[key]
    return info ? [{ key, what, loaded: info.loaded, total: info.total }] : []
  }),
)

const expandedBuildings = ref(new Set<string>())
const expandedRooms = ref(new Set<string>())
function toggleBuilding(id: string) {
  if (expandedBuildings.value.has(id)) expandedBuildings.value.delete(id)
  else expandedBuildings.value.add(id)
}
function toggleRoom(id: string) {
  if (expandedRooms.value.has(id)) expandedRooms.value.delete(id)
  else expandedRooms.value.add(id)
}

function roomsOf(buildingId: string): Room[] {
  return ((catalogs.items['rooms'] ?? []) as unknown as Room[]).filter((r) => r.building_id === buildingId)
}
function racksOf(roomId: string): Rack[] {
  return ((catalogs.items['racks'] ?? []) as unknown as Rack[]).filter((r) => r.room_id === roomId)
}

const buildingModal = ref<{ open: boolean; item: Building | null }>({ open: false, item: null })
const roomModal = ref<{ open: boolean; item: Room | null; buildingId: string }>({ open: false, item: null, buildingId: '' })
const rackModal = ref<{ open: boolean; item: Rack | null; roomId: string }>({ open: false, item: null, roomId: '' })

function openCreateBuilding() {
  buildingModal.value = { open: true, item: null }
}
function openEditBuilding(b: Building) {
  buildingModal.value = { open: true, item: b }
}
function openCreateRoom(buildingId: string) {
  roomModal.value = { open: true, item: null, buildingId }
  expandedBuildings.value.add(buildingId)
}
function openEditRoom(r: Room) {
  roomModal.value = { open: true, item: r, buildingId: r.building_id }
}
function openCreateRack(roomId: string) {
  rackModal.value = { open: true, item: null, roomId }
  expandedRooms.value.add(roomId)
}
function openEditRack(r: Rack) {
  rackModal.value = { open: true, item: r, roomId: r.room_id }
}

async function afterSave(message: string) {
  buildingModal.value.open = false
  roomModal.value.open = false
  rackModal.value.open = false
  await catalogs.reload()
  notify(message, 'success')
}

async function removeBuilding(b: Building) {
  if (!confirm(`Удалить здание «${b.name}»? Все связанные помещения и стойки должны быть удалены заранее.`)) return
  try {
    await deleteResource('buildings', b.id)
    await catalogs.reload()
    notify('Здание удалено', 'success')
  } catch (err) {
    notifyError(err)
  }
}
async function removeRoom(r: Room) {
  if (!confirm(`Удалить помещение «${r.name}»?`)) return
  try {
    await deleteResource('rooms', r.id)
    await catalogs.reload()
    notify('Помещение удалено', 'success')
  } catch (err) {
    notifyError(err)
  }
}
async function removeRack(r: Rack) {
  if (!confirm(`Удалить стойку «${r.name}»?`)) return
  try {
    await deleteResource('racks', r.id)
    await catalogs.reload()
    notify('Стойка удалена', 'success')
  } catch (err) {
    notifyError(err)
  }
}
</script>

<template>
  <div class="buildings-view">
    <div class="toolbar">
      <p class="hint">Здания → помещения → стойки. Удаление здания/помещения возможно только когда в нём не осталось вложенных записей.</p>
      <button v-if="auth.canWrite" class="btn btn-primary" @click="openCreateBuilding">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Добавить здание
      </button>
    </div>

    <DataLoadNotice v-for="n in incompleteNotices" :key="n.key" kind="incomplete" :what="n.what" :loaded="n.loaded" :total="n.total" />
    <div v-if="catalogs.error" class="error-banner card">{{ catalogs.error }}</div>
    <div v-else-if="catalogs.loading && !catalogs.loaded" class="loading-banner">Загрузка…</div>
    <div v-else-if="!(catalogs.items['buildings'] ?? []).length" class="empty-banner card">Зданий пока нет в справочнике.</div>

    <div v-else class="tree">
      <div v-for="b in catalogs.items['buildings'] ?? []" :key="b.id" class="building card">
        <div class="row building-row">
          <button type="button" class="expand-btn" @click="toggleBuilding(b.id)">
            <svg class="icon chev" :class="{ open: expandedBuildings.has(b.id) }"><use href="/icons.svg#i-chevd" /></svg>
          </button>
          <svg class="icon type-icon"><use href="/icons.svg#i-building" /></svg>
          <div class="row-main">
            <span class="row-name">{{ b.name }}</span>
            <span v-if="b.address" class="row-sub">{{ b.address }}</span>
          </div>
          <span class="count-badge">{{ roomsOf(b.id).length }} помещ.</span>
          <div class="row-actions">
            <button v-if="auth.canWrite" type="button" aria-label="Добавить помещение" @click="openCreateRoom(b.id)">
              <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
            </button>
            <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEditBuilding(b)">
              <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
            </button>
            <button v-if="auth.canWrite" type="button" aria-label="Удалить" @click="removeBuilding(b)">
              <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
            </button>
          </div>
        </div>

        <div v-if="expandedBuildings.has(b.id)" class="rooms">
          <p v-if="!roomsOf(b.id).length" class="empty-nested">Помещений пока нет.</p>
          <div v-for="r in roomsOf(b.id)" :key="r.id" class="room">
            <div class="row room-row">
              <button type="button" class="expand-btn" @click="toggleRoom(r.id)">
                <svg class="icon chev" :class="{ open: expandedRooms.has(r.id) }"><use href="/icons.svg#i-chevd" /></svg>
              </button>
              <span class="row-name">{{ r.name }}</span>
              <span class="count-badge">{{ racksOf(r.id).length }} стоек</span>
              <div class="row-actions">
                <button v-if="auth.canWrite" type="button" aria-label="Добавить стойку" @click="openCreateRack(r.id)">
                  <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                </button>
                <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEditRoom(r)">
                  <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
                </button>
                <button v-if="auth.canWrite" type="button" aria-label="Удалить" @click="removeRoom(r)">
                  <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                </button>
              </div>
            </div>

            <div v-if="expandedRooms.has(r.id)" class="racks">
              <p v-if="!racksOf(r.id).length" class="empty-nested">Стоек пока нет.</p>
              <div v-for="rack in racksOf(r.id)" :key="rack.id" class="row rack-row">
                <span class="row-name">{{ rack.name }}</span>
                <span v-if="rack.height_u" class="mono rack-height">{{ rack.height_u }}U</span>
                <div class="row-actions">
                  <button type="button" :aria-label="auth.canWrite ? 'Редактировать' : 'Просмотр'" @click="openEditRack(rack)">
                    <svg class="icon"><use :href="auth.canWrite ? '/icons.svg#i-edit' : '/icons.svg#i-file'" /></svg>
                  </button>
                  <button v-if="auth.canWrite" type="button" aria-label="Удалить" @click="removeRack(rack)">
                    <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <BuildingFormModal
      v-if="buildingModal.open"
      :building="buildingModal.item"
      @close="buildingModal.open = false"
      @saved="afterSave(buildingModal.item ? 'Здание обновлено' : 'Здание добавлено')"
    />
    <RoomFormModal
      v-if="roomModal.open"
      :room="roomModal.item"
      :building-id="roomModal.buildingId"
      @close="roomModal.open = false"
      @saved="afterSave(roomModal.item ? 'Помещение обновлено' : 'Помещение добавлено')"
    />
    <RackFormModal
      v-if="rackModal.open"
      :rack="rackModal.item"
      :room-id="rackModal.roomId"
      @close="rackModal.open = false"
      @saved="afterSave(rackModal.item ? 'Стойка обновлена' : 'Стойка добавлена')"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 0;
  max-width: 60ch;
}
.error-banner,
.empty-banner {
  padding: 20px;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.loading-banner {
  padding: 24px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.tree {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.building {
  padding: 0;
  overflow: hidden;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
}
.building-row {
  background: var(--surface);
}
.expand-btn {
  background: none;
  border: none;
  padding: 2px;
  color: var(--ink-muted);
  flex-shrink: 0;
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform 0.15s;
}
.chev.open {
  transform: rotate(180deg);
}
.type-icon {
  width: 16px;
  height: 16px;
  color: var(--brand);
  flex-shrink: 0;
}
.row-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.row-name {
  font-weight: 600;
  font-size: 13px;
}
.row-sub {
  font-size: 11px;
  color: var(--ink-muted);
}
.count-badge {
  font-size: 10.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 2px 9px;
  white-space: nowrap;
}
.row-actions {
  display: flex;
  gap: 2px;
  margin-left: auto;
}
.row-actions button {
  background: none;
  border: none;
  padding: 5px;
  color: var(--ink-muted);
  border-radius: var(--r-s);
}
.row-actions button:hover {
  background: var(--surface-2);
  color: var(--ink);
}
.row-actions .icon {
  width: 13px;
  height: 13px;
  display: block;
}
.rooms {
  border-top: 1px solid var(--border);
  background: var(--bg);
  padding-left: 14px;
}
.room-row {
  padding-left: 6px;
}
.racks {
  border-top: 1px solid var(--border);
  padding-left: 20px;
}
.rack-row {
  padding: 8px 14px;
}
.rack-row .row-name {
  font-weight: 500;
  font-size: 12.5px;
}
.rack-height {
  color: var(--ink-muted);
  font-size: 11px;
}
.empty-nested {
  font-size: 11.5px;
  color: var(--ink-muted);
  font-style: italic;
  padding: 8px 14px;
  margin: 0;
}
</style>
