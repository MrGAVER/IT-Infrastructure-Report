import { mergeConfig } from 'vite'
import { configDefaults, defineConfig as defineVitestConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineVitestConfig({
    test: {
      // e2e/ — проверки Playwright (npm run e2e): у них свой раннер, vitest их запускать не должен.
      exclude: [...configDefaults.exclude, 'e2e/**'],
      environment: 'jsdom',
      // Каждый тестовый файл по-прежнему получает собственное окружение (изоляция сохранена), но создаётся оно не новым
      // процессом на файл, а контекстом vm в потоке: прогон 167 файлов (2446 тестов) ускорился с ~222 с до ~50 с (−77%),
      // 65% прежнего времени уходило на создание окружения jsdom (замеры B-13, 2 ядра). Проверено: стабильно в TZ=UTC и
      // Europe/Minsk и при случайном порядке (--sequence.shuffle). Если тест начнёт вести себя странно из-за общих
      // встроенных объектов между контекстами (instanceof, Date), вернуть `pool: 'forks'`.
      pool: 'vmThreads',
      // Теги тестов. `slow` — замер времени или нагрузочная проверка (как маркер `slow` у pytest): выполняется по умолчанию, исключить
      // можно ключом `--tags-filter '!slow'` (npm run test:fast). Незнакомый тег в тесте — ошибка (strictTags), опечатка не пройдёт молча.
      tags: [{ name: 'slow', description: 'Замер времени или нагрузочная проверка; npm run test:fast их пропускает.' }],
      globals: true,
      // Teleport окон (BaseModal) заменён заглушкой — см. комментарий в файле.
      setupFiles: ['./src/__tests__/setup.ts'],
      css: false,
      // Стабы vi.stubGlobal (fetch, confirm и т.п.) не должны переживать границу
      // теста по умолчанию — иначе тест может случайно пройти на стабе, оставшемся
      // от предыдущего теста, вместо своего собственного (наступили на это в
      // DeviceFormModal.spec.ts при живой разработке).
      unstubGlobals: true,
    },
  }),
)
