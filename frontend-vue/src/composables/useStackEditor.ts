// Окно стека и удаление на дашборде «Стеки устройств»: открыть для создания/правки, закрыть с перечиткой, удалить с подтверждением.
// Вынесено из DeviceStacksView.vue без изменения поведения.
import { ref } from 'vue'
import { deleteResource } from '../api/client'
import type { DeviceStack } from '../api/types'
import { useDeviceStacksStore } from '../stores/deviceStacks'
import { useToast } from './useToast'

/** `refreshVlans` — сбросить кэш общих VLAN раскрытых строк (их меняют в окне стека). */
export function useStackEditor(refreshVlans: () => void) {
  const stacks = useDeviceStacksStore()
  const { notify, notifyError } = useToast()

  const modalStack = ref<DeviceStack | null>(null)
  const modalOpen = ref(false)
  const deletingId = ref<string | null>(null)

  function openCreate() {
    modalStack.value = null
    modalOpen.value = true
  }
  function openEdit(s: DeviceStack) {
    modalStack.value = s
    modalOpen.value = true
  }
  /** Перечитать всё, что показывает экран: стеки и устройства — и общие VLAN раскрытых строк (в окне стека их меняют). */
  function refresh() {
    refreshVlans()
    void stacks.reloadWithDevices()
  }
  function closeModal() {
    modalOpen.value = false
    modalStack.value = null
    // Состав стека меняется прямо в окне (добавить/убрать устройство применяется сразу), а таблица строится из реестра
    // устройств, поэтому при любом закрытии окна — в том числе крестиком — перечитываются и стеки, и устройства.
    refresh()
  }
  function onSaved() {
    const wasEdit = modalStack.value !== null
    closeModal()
    notify(wasEdit ? 'Стек обновлён' : 'Стек добавлен', 'success')
  }

  async function removeStack(s: DeviceStack) {
    if (!confirm(`Удалить стек «${s.name}»?`)) return
    deletingId.value = s.id
    try {
      await deleteResource('device-stacks', s.id)
      await stacks.reload()
      notify('Стек удалён', 'success')
    } catch (err) {
      // Стек с участниками delete_resource не удалит (REFERENCED_BY_OTHER_RECORDS) — сообщение с
      // бэкенда уже объясняет, что сперва нужно убрать устройства из стека.
      notifyError(err)
    } finally {
      deletingId.value = null
    }
  }

  return { modalStack, modalOpen, deletingId, openCreate, openEdit, refresh, closeModal, onSaved, removeStack }
}
