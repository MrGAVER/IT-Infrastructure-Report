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
