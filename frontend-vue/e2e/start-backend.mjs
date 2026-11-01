// Запуск backend для e2e-проверок (Playwright webServer, см. playwright.config.ts): чистая SQLite во временном каталоге,
// миграции Alembic, затем uvicorn, который раздаёт собранный frontend-vue/dist — ровно как в боевом запуске, включая CSP.
// Рабочая база и каталог отчётов разработчика не затрагиваются: всё лежит во временном каталоге и удаляется при остановке.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backendDir = path.resolve(frontendDir, '..', 'backend')
const distDir = path.join(frontendDir, 'dist')
const port = process.env.E2E_PORT ?? '8765'
// Интерпретатор с зависимостями backend (venv разработчика или Python из CI); по умолчанию — первый в PATH.
const python = process.env.E2E_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')

if (!existsSync(path.join(distDir, 'index.html'))) {
  console.error(`Нет ${distDir}/index.html — соберите фронтенд (npm run build) или запускайте проверки через npm run e2e.`)
  process.exit(1)
}

const dataDir = mkdtempSync(path.join(tmpdir(), 'itr-e2e-'))
const databasePath = path.join(dataDir, 'e2e.db').split(path.sep).join('/')
const env = {
  ...process.env,
  // sqlite:/// + абсолютный путь: на Linux/macOS получается sqlite:////tmp/…, на Windows — sqlite:///C:/…
  DATABASE_URL: `sqlite:///${databasePath}`,
  INFRA_REGISTRY_DB_HOST: '',
  INFRA_REGISTRY_DATA_DIR: dataDir,
  INFRA_REGISTRY_FRONTEND_DIR: distDir,
}

function cleanup() {
  rmSync(dataDir, { recursive: true, force: true })
}

const migration = spawnSync(python, ['-m', 'alembic', 'upgrade', 'head'], { cwd: backendDir, env, stdio: 'inherit' })
if (migration.status !== 0) {
  console.error(
    `alembic upgrade head завершился с кодом ${migration.status} (интерпретатор: ${python}; задайте E2E_PYTHON, если зависимости backend стоят в venv).`,
  )
  cleanup()
  process.exit(migration.status ?? 1)
}

const server = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], { cwd: backendDir, env, stdio: 'inherit' })
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.kill(signal))
server.on('exit', (code) => {
  cleanup()
  process.exit(code ?? 0)
})
