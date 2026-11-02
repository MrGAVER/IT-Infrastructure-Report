import { defineConfig } from '@playwright/test'

// E2E-проверки интерфейса в настоящем браузере (Chromium). Юнит-тесты (vitest + jsdom) раскладку не считают, поэтому дефекты
// вёрстки — обрезанное мобильное меню, пустые иконки, внешние запросы за шрифтами — ловятся только здесь. Запуск: npm run e2e.
// Ревью merge/review-2158-executors, раздел «Рекомендации», пункт 3.
const port = process.env.E2E_PORT ?? '8765'
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // Тесты в основном ждут браузер и сеть, а не считают, поэтому на 2-ядерном раннере CI два воркера укладываются в ~1,5 мин.
  workers: process.env.CI ? 2 : undefined,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Свой Chromium вместо скачанного Playwright (закрытый контур, образ без доступа к CDN): E2E_CHROMIUM_PATH=/путь/к/chrome.
    launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH || undefined },
  },
  // backend поднимается на чистой временной SQLite (e2e/start-backend.mjs) и раздаёт собранный dist с боевым CSP. Уже запущенный
  // сервер на этом порту повторно не используется — иначе проверки пошли бы по чужим данным; для отладки: E2E_REUSE_SERVER=1.
  webServer: {
    command: 'node e2e/start-backend.mjs',
    url: `${baseURL}/api/v1/health`,
    reuseExistingServer: process.env.E2E_REUSE_SERVER === '1',
    timeout: 120_000,
    // Журнал uvicorn шумный (по строке на каждый запрос); для разбора падений: E2E_SERVER_LOGS=1.
    stdout: process.env.E2E_SERVER_LOGS ? 'pipe' : 'ignore',
    stderr: process.env.E2E_SERVER_LOGS ? 'pipe' : 'ignore',
  },
})
