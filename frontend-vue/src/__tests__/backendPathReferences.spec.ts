// B-06 (ревью merge/review-r1-r2-executors): после нарезки одноимённого модуля auth на пакет services/auth/ семь комментариев во
// frontend продолжали ссылаться на несуществующий файл (то же случилось и с модулем crud, ставшим пакетом). Комментарии с путями на backend — единственная связь между двумя частями
// репозитория, которую не проверяет ни компилятор, ни линтер, поэтому проверяет этот тест: каждый путь `backend/app/….py`, упомянутый
// в исходниках frontend, обязан существовать.
//
// Как и проверка ErrorCode в api/__tests__/client.spec.ts, тест пропускается, если рядом нет каталога backend (frontend собирают отдельно).
import { describe, expect, it } from 'vitest'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(here, '..')
const repoRoot = resolve(srcDir, '../..')
const backendApp = join(repoRoot, 'backend', 'app')

/** Файлы исходников frontend (ts, vue), кроме зависимостей. */
function* sourceFiles(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name !== 'node_modules') yield* sourceFiles(path)
    } else if (/\.(ts|vue)$/.test(name)) {
      yield path
    }
  }
}

// Путь `backend/app/<каталоги>/<модуль>.py`; символ после двоеточия (`:require_setup_access`) в путь не входит.
const BACKEND_PATH = /backend\/app\/[A-Za-z0-9_/]+\.py/g

describe.skipIf(!existsSync(backendApp))('B-06: ссылки frontend на файлы backend ведут на существующие файлы', () => {
  const references = new Map<string, string[]>() // путь → файлы frontend, где он упомянут
  for (const file of sourceFiles(srcDir)) {
    for (const match of readFileSync(file, 'utf-8').matchAll(BACKEND_PATH)) {
      const users = references.get(match[0]) ?? []
      if (!users.includes(file)) users.push(file)
      references.set(match[0], users)
    }
  }

  it('в исходниках есть ссылки на backend (иначе проверка ничего не проверяет)', () => {
    expect(references.size).toBeGreaterThan(5)
  })

  it('каждый упомянутый путь backend/app/….py существует', () => {
    const missing = [...references]
      .filter(([path]) => !existsSync(join(repoRoot, path)))
      .map(([path, files]) => `${path} ← ${files.map((f) => f.slice(srcDir.length + 1)).join(', ')}`)

    expect(missing).toEqual([])
  })

  it('модуль auth, ставший пакетом services/auth/, нигде не упоминается как один файл', () => {
    const stale = ['backend', 'app', 'services', 'auth.py'].join('/') // собирается из частей, чтобы тест не находил сам себя
    expect([...references.keys()]).not.toContain(stale)
  })
})
