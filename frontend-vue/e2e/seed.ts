import type { APIRequestContext } from '@playwright/test'

// Наполнение приложения данными через API для e2e-проверок на ЗАПОЛНЕННЫХ экранах. Прежние проверки ходили только по пустой базе, поэтому
// дефекты, которые видны лишь при данных (диаграмма не вписывается в холст, длинные формы), в них не проявлялись (ревью 2.158.0, §5).
// Данные создаются по API, а не через интерфейс: так проверка не зависит от форм, которые сама же и проверяет.

const ORIGIN = `http://127.0.0.1:${process.env.E2E_PORT ?? '8765'}`
const API = '/api/v1'

interface Catalog {
  items?: Array<{ id: string; name: string }>
}

async function postJson<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  // Origin обязателен: backend проверяет его у небезопасных методов (CSRF), браузерный fetch проставляет его сам.
  const response = await request.post(`${API}${path}`, { data, headers: { Origin: ORIGIN } })
  if (!response.ok()) throw new Error(`POST ${path} → ${response.status()}: ${(await response.text()).slice(0, 200)}`)
  return (await response.json()) as T
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
  const interfaces = (await all.json()) as { items?: Array<{ id: string; name: string; physical_device_id: string }> } | Array<{ id: string; name: string; physical_device_id: string }>
  const rows = Array.isArray(interfaces) ? interfaces : (interfaces.items ?? [])
  const byDevice = (deviceId: string) => rows.filter((row) => row.physical_device_id === deviceId).sort((x, y) => x.name.localeCompare(y.name, 'en', { numeric: true }))
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
