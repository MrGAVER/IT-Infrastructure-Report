// Обход исходников frontend для тестов-«стражей» (backendPathReferences.spec.ts, securityPolicy.spec.ts): они проверяют не поведение,
// а то, что в коде нет того, чего быть не должно (устаревших ссылок, лишних способов вставки HTML).
import { readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

/** Каталог src. */
export const srcDir = resolve(here, '..')

/** Файлы исходников frontend (ts, vue), кроме зависимостей; с includeTests = false — ещё и без тестов (каталоги __tests__, *.spec.ts). */
export function* sourceFiles(dir: string = srcDir, includeTests = true): Generator<string> {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name !== 'node_modules' && (includeTests || name !== '__tests__')) yield* sourceFiles(path, includeTests)
    } else if (/\.(ts|vue)$/.test(name) && (includeTests || !/\.spec\.ts$/.test(name))) {
      yield path
    }
  }
}

/** Путь относительно src с прямыми слэшами — для сообщений об ошибках и списков-исключений. */
export function relativeToSrc(file: string): string {
  return file.slice(srcDir.length + 1).replaceAll('\\', '/')
}
