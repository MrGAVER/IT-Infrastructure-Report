import type { APIRequestContext } from '@playwright/test'

// Наполнение приложения данными через API для e2e-проверок на ЗАПОЛНЕННЫХ экранах. Прежние проверки ходили только по пустой базе, поэтому
// дефекты, которые видны лишь при данных (диаграмма не вписывается в холст, длинные формы), в них не проявлялись (ревью 2.158.0, §5).
// Данные создаются по API, а не через интерфейс: так проверка не зависит от форм, которые сама же и проверяет.

const ORIGIN = `http://127.0.0.1:${process.env.E2E_PORT ?? '8765'}`
const API = '/api/v1'

interface Catalog {
  items?: Array<{ id: string; name: string }>
}

// Пути DELETE созданных фикстурами ресурсов — в порядке создания. База у всех тестов прогона общая: без уборки устройства из одного
// теста попадали бы на экраны, которые другие тесты проверяют на пустой базе (так «/devices шире окна» всплыло в routes.spec.ts).
const created: string[] = []

async function postJson<T extends { id?: string }>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  // Origin обязателен: backend проверяет его у небезопасных методов (CSRF), браузерный fetch проставляет его сам.
  const response = await request.post(`${API}${path}`, { data, headers: { Origin: ORIGIN } })
  if (!response.ok()) throw new Error(`POST ${path} → ${response.status()}: ${(await response.text()).slice(0, 200)}`)
  const body = (await response.json()) as T
  if (body.id) created.push(`${API}${path}/${body.id}`)
  return body
}

/**
 * Удаляет всё, что создали фикстуры этого файла, в обратном порядке (диаграмма → подключения → устройства → здание). Вызывать в
 * test.afterEach. 404 не ошибка (ресурс уже удалён каскадом); любой другой отказ — ошибка: молчаливая утечка данных в общую базу
 * ломала бы чужие тесты непредсказуемо.
 */
export async function cleanupSeeded(request: APIRequestContext): Promise<void> {
  const failures: string[] = []
  for (const path of created.splice(0).reverse()) {
    // Устройство с интерфейсами backend не удаляет (409 REFERENCED_BY_OTHER_RECORDS) — сначала очищаем их; подключения к этому
    // моменту уже удалены (обратный порядок), иначе интерфейсы тоже были бы заняты.
    const device = /\/resources\/devices\/([^/]+)$/.exec(path)
    if (device) await request.put(`${API}/devices/${device[1]}/interfaces`, { data: { interfaces: [] }, headers: { Origin: ORIGIN } })
    const response = await request.delete(path, { headers: { Origin: ORIGIN } })
    if (!response.ok() && response.status() !== 404) failures.push(`DELETE ${path} → ${response.status()}`)
  }
  if (failures.length) throw new Error(`не удалось убрать данные фикстур: ${failures.join('; ')}`)
}

async function deviceTypeIds(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(`${API}/resources/device-types`)
  const body = (await response.json()) as Catalog | Array<{ id: string }>
  const items = Array.isArray(body) ? body : (body.items ?? [])
  if (items.length === 0) throw new Error('справочник типов устройств пуст — миграции не наполнили его')
  return items.map((item) => item.id)
}

let counter = 0

/**
 * Создаёт диаграмму топологии на заданном числе устройств разных типов и возвращает её id. Устройств по умолчанию 30:
 * этого хватает, чтобы сетка узлов вышла за размеры холста и на 1440 px, и на 390 px — иначе проверка «диаграмма вписана»
 * доказывала бы только то, что маленький граф и так помещается.
 */
export async function seedDiagram(request: APIRequestContext, options: { devices?: number } = {}): Promise<string> {
  const devices = options.devices ?? 30
  const types = await deviceTypeIds(request)
  const run = `${Date.now().toString(36)}-${counter++}`
  for (let index = 0; index < devices; index++) {
    await postJson(request, '/resources/devices', {
      device_type_id: types[index % types.length],
      system_name: `e2e-${run}-${index}`,
      serial_number: `E2E-${run}-${index}`,
    })
  }
  const diagram = await postJson<{ id: string }>(request, '/diagrams', {
    name: `e2e-диаграмма-${run}`,
    scope_filter: {},
    group_by: 'device_category',
    collapse_threshold: 500,
  })
  return diagram.id
}

/**
 * Виртуальная машина с заданным назначением для проверок редактирования (без хоста и ОС: форме они не нужны). Название уникально в
 * прогоне — база общая для параллельных тестов. Убирается cleanupSeeded().
 */
export async function seedVirtualMachine(request: APIRequestContext, options: { purpose: string }): Promise<{ id: string; name: string }> {
  const name = `e2e-vm-${Date.now().toString(36)}-${counter++}`
  const vm = await postJson<{ id: string }>(request, '/resources/vms', { name, purpose: options.purpose })
  return { id: vm.id, name }
}

/**
 * Диаграмма из двух коммутаторов с `links` параллельными связями между соседними портами (0…links − 1 на обоих концах) — именно
 * так подписи портов у соседних засечек наслаиваются друг на друга (UI-22). Возвращает id диаграммы.
 */
export async function seedParallelLinks(request: APIRequestContext, options: { links: number }): Promise<string> {
  const [typeId] = await deviceTypeIds(request)
  const run = `${Date.now().toString(36)}-${counter++}`
  // База общая для всех тестов прогона, а фильтр диаграммы не умеет «только эти устройства» — изолируем отдельным зданием.
  const building = await postJson<{ id: string }>(request, '/resources/buildings', { name: `e2e-здание-${run}`, address: 'e2e' })
  const devices: Array<{ id: string }> = []
  for (const side of ['a', 'b']) {
    const device = await postJson<{ id: string }>(request, '/resources/devices', {
      device_type_id: typeId,
      system_name: `e2e-link-${run}-${side}`,
      serial_number: `E2E-LINK-${run}-${side}`,
      building_id: building.id,
    })
    const interfaces = Array.from({ length: 8 }, (_, index) => ({ name: `Gi1/0/${index + 1}`, is_management: false, ips: [] }))
    const put = await request.put(`${API}/devices/${device.id}/interfaces`, { data: { interfaces }, headers: { Origin: ORIGIN } })
    if (!put.ok()) throw new Error(`PUT interfaces → ${put.status()}`)
    devices.push(device)
  }

  const connectionTypes = (await (await request.get(`${API}/resources/connection-types`)).json()) as Catalog | Array<{ id: string }>
  const connectionTypeId = (Array.isArray(connectionTypes) ? connectionTypes : (connectionTypes.items ?? []))[0]?.id
  const all = await request.get(`${API}/resources/interfaces?limit=1000`)
  const interfaces = (await all.json()) as
    { items?: Array<{ id: string; name: string; physical_device_id: string }> } | Array<{ id: string; name: string; physical_device_id: string }>
  const rows = Array.isArray(interfaces) ? interfaces : (interfaces.items ?? [])
  const byDevice = (deviceId: string) =>
    rows.filter((row) => row.physical_device_id === deviceId).sort((x, y) => x.name.localeCompare(y.name, 'en', { numeric: true }))
  const [left, right] = [byDevice(devices[0].id), byDevice(devices[1].id)]
  for (let index = 0; index < options.links; index++) {
    await postJson(request, '/resources/connections', {
      source_interface_id: left[index].id,
      destination_interface_id: right[index].id,
      connection_type_id: connectionTypeId,
    })
  }

  const diagram = await postJson<{ id: string }>(request, '/diagrams', {
    name: `e2e-связи-${run}`,
    scope_filter: { building_ids: [building.id] },
    group_by: 'device_category',
    collapse_threshold: 500,
  })
  return diagram.id
}

/**
 * Диаграмма «сетка узлов со связями» для проверки рёбер (код-ревью main, F-07): `devices` устройств по 8 интерфейсов, «хребет» от первого
 * ко всем, связи между соседями и несколько связей «через ряд» — так рёбра идут и вдоль рядов, и между рядами, и через чужие узлы.
 * Узлов 18 по умолчанию: на такой схеме рёбра до правки проходили сквозь 16 узлов из 22. Каждый интерфейс занят не более одной связью.
 * Устройства лежат в отдельном здании, чтобы фильтр диаграммы не захватил данные других тестов. Возвращает id диаграммы и число связей.
 */
export async function seedTopology(request: APIRequestContext, options: { devices?: number } = {}): Promise<{ diagramId: string; links: number }> {
  const count = options.devices ?? 18
  const types = await deviceTypeIds(request)
  const run = `${Date.now().toString(36)}-${counter++}`
  const building = await postJson<{ id: string }>(request, '/resources/buildings', { name: `e2e-здание-${run}`, address: 'e2e' })
  const devices: Array<{ id: string }> = []
  for (let index = 0; index < count; index++) {
    const device = await postJson<{ id: string }>(request, '/resources/devices', {
      device_type_id: types[index % types.length],
      system_name: `e2e-topology-${run}-${String(index).padStart(2, '0')}`,
      serial_number: `E2E-TOPOLOGY-${run}-${index}`,
      building_id: building.id,
    })
    const interfaces = Array.from({ length: 8 }, (_, port) => ({ name: `Gi1/0/${port + 1}`, is_management: false, ips: [] }))
    const put = await request.put(`${API}/devices/${device.id}/interfaces`, { data: { interfaces }, headers: { Origin: ORIGIN } })
    if (!put.ok()) throw new Error(`PUT interfaces → ${put.status()}`)
    devices.push(device)
  }

  const connectionTypes = (await (await request.get(`${API}/resources/connection-types`)).json()) as Catalog | Array<{ id: string }>
  const connectionTypeId = (Array.isArray(connectionTypes) ? connectionTypes : (connectionTypes.items ?? []))[0]?.id
  const all = await request.get(`${API}/resources/interfaces?limit=1000`)
  const interfaces = (await all.json()) as
    { items?: Array<{ id: string; name: string; physical_device_id: string }> } | Array<{ id: string; name: string; physical_device_id: string }>
  const rows = Array.isArray(interfaces) ? interfaces : (interfaces.items ?? [])
  const free = new Map<string, string[]>()
  for (const device of devices) {
    free.set(
      device.id,
      rows
        .filter((row) => row.physical_device_id === device.id)
        .sort((x, y) => x.name.localeCompare(y.name, 'en', { numeric: true }))
        .map((row) => row.id),
    )
  }

  const pairs: Array<[number, number]> = []
  for (let i = 1; i < count; i++) pairs.push([0, i])
  for (let i = 1; i < count - 1; i += 2) pairs.push([i, i + 1])
  pairs.push([2, 8], [3, 9], [4, 13], [5, 12], [6, 15], [7, 16])
  let links = 0
  for (const [a, b] of pairs) {
    if (a === b || b >= count) continue
    const source = free.get(devices[a].id)?.shift()
    const destination = free.get(devices[b].id)?.shift()
    if (!source || !destination) continue
    await postJson(request, '/resources/connections', {
      source_interface_id: source,
      destination_interface_id: destination,
      connection_type_id: connectionTypeId,
    })
    links++
  }

  const diagram = await postJson<{ id: string }>(request, '/diagrams', {
    name: `e2e-топология-${run}`,
    scope_filter: { building_ids: [building.id] },
    group_by: 'device_category',
    collapse_threshold: 500,
  })
  return { diagramId: diagram.id, links }
}

/**
 * Подключение между двумя устройствами, у портов которого разные роли (источник — «Передача данных», приёмник — «Управление
 * активами»): при его сохранении форма показывает блок «Расхождение конфигурации портов» (ConnectionResolutionPanel). Устройства лежат
 * в отдельном здании. Возвращает системное имя устройства-источника: по нему строка находится в таблице подключений.
 */
export async function seedMismatchedConnection(request: APIRequestContext): Promise<{ sourceName: string }> {
  const [typeId] = await deviceTypeIds(request)
  const run = `${Date.now().toString(36)}-${counter++}`
  const building = await postJson<{ id: string }>(request, '/resources/buildings', { name: `e2e-здание-${run}`, address: 'e2e' })
  const devices: Array<{ id: string; system_name: string }> = []
  for (const side of ['a', 'b']) {
    const device = await postJson<{ id: string; system_name: string }>(request, '/resources/devices', {
      device_type_id: typeId,
      system_name: `e2e-resol-${run}-${side}`,
      serial_number: `E2E-RESOL-${run}-${side}`,
      building_id: building.id,
    })
    // Роль порта — единственное различие: у устройства «a» порт передаёт данные, у «b» — управляет активами.
    const interfaces = [{ name: 'Gi1/0/1', is_management: side === 'b', ips: [] }]
    const put = await request.put(`${API}/devices/${device.id}/interfaces`, { data: { interfaces }, headers: { Origin: ORIGIN } })
    if (!put.ok()) throw new Error(`PUT interfaces → ${put.status()}`)
    devices.push(device)
  }

  const connectionTypes = (await (await request.get(`${API}/resources/connection-types`)).json()) as Catalog | Array<{ id: string }>
  const connectionTypeId = (Array.isArray(connectionTypes) ? connectionTypes : (connectionTypes.items ?? []))[0]?.id
  const all = await request.get(`${API}/resources/interfaces?limit=1000`)
  const body = (await all.json()) as { items?: Array<{ id: string; physical_device_id: string }> } | Array<{ id: string; physical_device_id: string }>
  const rows = Array.isArray(body) ? body : (body.items ?? [])
  const [source, destination] = devices.map((device) => rows.find((row) => row.physical_device_id === device.id))
  if (!source || !destination) throw new Error('интерфейсы засеянных устройств не найдены')
  await postJson(request, '/resources/connections', {
    source_interface_id: source.id,
    destination_interface_id: destination.id,
    connection_type_id: connectionTypeId,
  })
  return { sourceName: devices[0].system_name }
}
