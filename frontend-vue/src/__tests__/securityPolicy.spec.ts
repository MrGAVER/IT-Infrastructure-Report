// B-05 (ревью merge/review-r1-r2-executors): токен сессии хранится в localStorage — принятый риск (frontend-vue/README.md, «Токен сессии
// в localStorage»). Принимать его можно, пока верны два утверждения, на которых держится обоснование:
//   1. Пользовательский HTML попадает в страницу только одним путём — SVG-иконки через v-html после очистки sanitizeSvg*/DOMPurify;
//   2. токен читается и пишется в одном месте — api/client.ts.
// Ни компилятор, ни линтер за этим не следят (правило vue/no-v-html выключено точечными комментариями), поэтому следит тест: новый
// v-html, прямая запись innerHTML или второй код, работающий с токеном, ломают его и заставляют пересмотреть принятый риск, а не обойти молча.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { relativeToSrc, sourceFiles } from './sourceFiles'

const sources = [...sourceFiles(undefined, false)].map((file) => ({ path: relativeToSrc(file), text: readFileSync(file, 'utf-8') }))

/** Единственные компоненты, которым разрешён v-html: оба показывают SVG-иконку устройства. Новый файл в списке — решение ревьюера. */
const V_HTML_ALLOWED = ['components/DeviceIconPicker.vue', 'components/diagram/DiagramDeviceNode.vue']

/** Тело объявления `const <name> = …` — до следующего объявления верхнего уровня. */
function declarationOf(text: string, name: string): string | null {
  const start = text.search(new RegExp(`^const ${name}\\b`, 'm'))
  if (start === -1) return null
  const rest = text.slice(start + 1)
  const next = rest.search(/^(?:const|let|function|export|watch|onMounted|<\/script>|\/\/ )/m)
  return text.slice(start, next === -1 ? undefined : start + 1 + next)
}

describe('B-05: допущения, на которых держится принятый риск «токен в localStorage»', () => {
  const withVHtml = sources.filter((s) => /\sv-html\s*=/.test(s.text))

  it('v-html есть только в компонентах SVG-иконок (иначе — пересмотреть принятый риск)', () => {
    expect(withVHtml.map((s) => s.path).sort()).toEqual([...V_HTML_ALLOWED].sort())
  })

  it('каждое значение, подставляемое в v-html, собрано вызовом sanitizeSvg / sanitizeSvgIsolated', () => {
    const unsafe: string[] = []
    for (const { path, text } of withVHtml) {
      for (const match of text.matchAll(/\sv-html\s*=\s*"([^"]+)"/g)) {
        const expression = match[1].trim()
        const declaration = /^[A-Za-z_$][\w$]*$/.test(expression) ? declarationOf(text, expression) : null
        if (!declaration || !/\bsanitizeSvg(?:Isolated)?\(/.test(declaration)) unsafe.push(`${path}: v-html="${expression}"`)
      }
    }

    expect(unsafe).toEqual([])
  })

  it('исходники не пишут HTML в DOM мимо шаблона: ни innerHTML/outerHTML =, ни insertAdjacentHTML, ни document.write', () => {
    const offenders = sources
      .filter(({ text }) => /\.(?:innerHTML|outerHTML)\s*\+?=(?!=)|\binsertAdjacentHTML\s*\(|\bdocument\.write(?:ln)?\s*\(/.test(text))
      .map((s) => s.path)

    expect(offenders).toEqual([])
  })

  it('ключ токена сессии (строковый литерал) встречается только в api/client.ts', () => {
    // Литерал, а не подстрока: комментарии вроде «токен (itr:auth-token) сюда не относится» (utils/localSettings.ts) — не код.
    const users = sources.filter(({ text }) => /['"`]itr:auth-token['"`]/.test(text)).map((s) => s.path)

    expect(users).toEqual(['api/client.ts'])
  })

  it('охранный тест различает опасное: на синтетических примерах находит и небезопасный v-html, и запись innerHTML', () => {
    expect(declarationOf('const a = computed(() => sanitizeSvg(x))\nconst b = 1', 'a')).toContain('sanitizeSvg(')
    expect(declarationOf('const a = computed(() => sanitizeSvg(x))\nconst b = raw', 'b')).not.toContain('sanitizeSvg(')
    expect(declarationOf('const a = 1', 'missing')).toBeNull()
    expect('el.innerHTML = markup').toMatch(/\.(?:innerHTML|outerHTML)\s*\+?=(?!=)/)
    expect('return body.innerHTML').not.toMatch(/\.(?:innerHTML|outerHTML)\s*\+?=(?!=)/)
    expect('if (el.innerHTML === "") {}').not.toMatch(/\.(?:innerHTML|outerHTML)\s*\+?=(?!=)/)
  })
})
