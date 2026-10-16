// Заголовок и «хлебные крошки» верхней панели для каждого именованного маршрута (см. router/index.ts).
// Вынесено из AppShell.vue, чтобы таблицу можно было проверить тестом: у каждого маршрута приложения
// (кроме экрана входа, который рисуется без оболочки) должен быть читаемый заголовок, а не техническое имя
// маршрута вроде «device-stacks» или «diagram-detail».

export interface PageHeading {
  title: string
  crumb: string
}

export const PAGE_TITLES: Record<string, PageHeading> = {
  dashboard: { title: 'Дашборд', crumb: 'Обзор' },
  'information-systems': { title: 'Информационные системы', crumb: 'Лист 1 · Информационные системы' },
  devices: { title: 'Инвентаризация физических устройств', crumb: 'Инвентаризация › Физические устройства' },
  'device-stacks': { title: 'Стеки устройств', crumb: 'Инвентаризация › Стеки устройств' },
  connections: { title: 'Подключения', crumb: 'Лист 3 · Подключения' },
  diagrams: { title: 'Диаграмма топологии сети', crumb: 'Диаграммы · Топология сети' },
  'diagram-detail': { title: 'Диаграмма топологии сети', crumb: 'Диаграммы · Топология сети · Просмотр' },
  vms: { title: 'Виртуальные машины', crumb: 'Лист 4 · Виртуальные машины' },
  containers: { title: 'Контейнеры', crumb: 'Лист 4 · Контейнеры' },
  vlans: { title: 'VLAN', crumb: 'Справочники · VLAN' },
  buildings: { title: 'Здания и помещения', crumb: 'Справочники · Здания и помещения' },
  'structural-units': { title: 'Структурные подразделения', crumb: 'Справочники · Структурные подразделения' },
  'other-catalogs': { title: 'Другие справочники', crumb: 'Справочники · Другие справочники' },
  reports: { title: 'Отчёты', crumb: 'Система · Отчёты' },
  'report-templates': { title: 'Шаблоны отчётов', crumb: 'Система · Отчёты · Шаблоны' },
  'report-template-editor': { title: 'Редактор шаблона', crumb: 'Система · Отчёты · Шаблоны · Редактор' },
  'report-template-editor-docx': { title: 'Редактор шаблона', crumb: 'Система · Отчёты · Шаблоны · Редактор' },
  'port-sync-rules': { title: 'Правила согласования портов', crumb: 'Система · Правила согласования портов' },
  'audit-log': { title: 'Журнал аудита', crumb: 'Система · Журнал аудита' },
  settings: { title: 'Настройки', crumb: 'Система › Настройки' },
}

/**
 * Заголовок верхней панели для маршрута. Для неизвестного имени — запасной вариант: `meta.title` маршрута,
 * а если его нет, то само имя (так новый маршрут без записи в таблице хотя бы не оставит панель пустой).
 */
export function resolvePageHeading(routeName: unknown, metaTitle?: unknown): PageHeading {
  const known = typeof routeName === 'string' ? PAGE_TITLES[routeName] : undefined
  if (known) return known
  return {
    title: typeof metaTitle === 'string' && metaTitle ? metaTitle : String(routeName ?? ''),
    crumb: '',
  }
}
