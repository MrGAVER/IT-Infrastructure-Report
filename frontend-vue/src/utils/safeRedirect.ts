// Адрес возврата после входа (?redirect=) приходит из адресной строки, то есть это ввод, которому нельзя доверять.
// vue-router воспринимает строку как внутренний путь приложения и на чужой сайт не уведёт (адрес собирается из
// текущего origin), но странные значения — `//host`, `/\host`, `/login`, `/%2e%2e/…`, очень длинные строки —
// приводят к предупреждениям роутера, циклу «вход → вход» или навигации на служебные пути. Это страховка
// (defense in depth), а не исправление уязвимости: пропускаем только обычные внутренние пути.

const MAX_REDIRECT_LENGTH = 512
/** Обратная косая черта и управляющие символы: браузеры нормализуют `/\host` в `//host`, а табуляция и перевод строки внутри адреса отбрасываются. */
const FORBIDDEN_CHARS = /[\\\u0000-\u001f\u007f]/

function decodePath(path: string): string | null {
  try {
    return decodeURIComponent(path)
  } catch {
    return null // некорректная %-последовательность
  }
}

/**
 * Возвращает `value`, если это безопасный внутренний путь приложения (`/devices?x=1`), иначе `fallback`.
 * Отклоняются: не строка (в том числе массив при повторяющемся параметре), пустая строка, длина больше 512,
 * не начинающийся с `/` или начинающийся с `//` (адрес без схемы — чужой сайт), с обратной косой чертой и
 * управляющими символами, с сегментами `.` и `..` (в том числе закодированными `%2e%2e`), а также сам экран
 * входа `/login` (после входа вернуться на него — значит остаться на нём).
 *
 * @example
 *   safeRedirect('/devices?x=1')        // '/devices?x=1'
 *   safeRedirect('//evil.example')      // '/dashboard'
 *   safeRedirect(['/a', '/b'], '/')     // '/'
 */
export function safeRedirect(value: unknown, fallback = '/dashboard'): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_REDIRECT_LENGTH) return fallback
  if (!value.startsWith('/') || value.startsWith('//') || FORBIDDEN_CHARS.test(value)) return fallback

  const path = decodePath(value.split(/[?#]/, 1)[0])
  // Проверки повторяются для раскодированного пути: `%2f%2fhost`, `%5c`, `%6cogin` не должны обходить правила выше.
  if (path === null || path.startsWith('//') || FORBIDDEN_CHARS.test(path)) return fallback
  if (path.split('/').some((segment) => segment === '.' || segment === '..')) return fallback
  if (path === '/login' || path.startsWith('/login/')) return fallback
  return value
}
