// Линтер фронтенда (ESLint 10, flat config). Набор намеренно минимальный: ловит ошибки и закрепляет
// проектные соглашения (см. WP-B, B-06), но не навязывает стиль — форматирование отдаётся Prettier
// (eslint-config-prettier отключает конфликтующие правила). Типы проверяет vue-tsc, а не линтер.
import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import prettier from 'eslint-config-prettier'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'test-results/**', 'playwright-report/**'] },

  js.configs.recommended,
  tseslint.configs.recommended,
  // essential — только правила против ошибок (не стилистика): v-for без key, дублирующиеся атрибуты и т.п.
  pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  {
    // Служебные node-скрипты (scripts/): не часть приложения, запускаются из CI и командной строки; console — их вывод.
    files: ['scripts/**/*.mjs'],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // Пользовательская разметка через v-html — путь к XSS. Допустимо только после sanitizeSvg(),
      // и каждое такое место помечается eslint-disable-next-line с объяснением (см. DiagramDeviceNode.vue).
      'vue/no-v-html': 'error',
      // Событие, не объявленное в defineEmits, не попадает в проверку типов и документацию компонента.
      'vue/require-explicit-emits': 'error',
      'vue/require-v-for-key': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      // console.log/debug/info — отладочный мусор; warn и error оставлены: это осознанные dev-предупреждения о неверном
      // использовании компонента (формы с одновременно переданными item и copyFrom).
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // `interface DeviceType extends CatalogItem {}` — именованный синоним справочной записи; пустое тело допустимо.
      '@typescript-eslint/no-empty-object-type': ['error', { allowInterfaces: 'with-single-extends' }],
      // Корневые макеты приложения (layout/Sidebar.vue, Topbar.vue): переименовывать ради стилистики незачем.
      'vue/multi-word-component-names': ['error', { ignores: ['Sidebar', 'Topbar'] }],
      // Для `_`-параметров и деструктуризации «выкинуть поле» — принятый приём; настоящие неиспользуемые остаются ошибкой.
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none', ignoreRestSiblings: true }],
    },
  },
  {
    // Даты с сервера — naive UTC; `new Date('2026-10-19T18:08:54')` трактуется как ЛОКАЛЬНОЕ время браузера и сдвигает
    // значение на часовой пояс пользователя (B-03). Разбор и форматирование — только через utils/dateTime.ts.
    files: ['src/**/*.{ts,vue}'],
    ignores: ['src/utils/dateTime.ts', 'src/**/__tests__/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "NewExpression[callee.name='Date'][arguments.length>0]",
          message: 'Дату с сервера разбирайте через parseServerDate() из utils/dateTime.ts: new Date(строка) трактует время без смещения как локальное.',
        },
        {
          selector: "CallExpression[callee.object.name='Date'][callee.property.name='parse']",
          message: 'Используйте parseServerDate() из utils/dateTime.ts: Date.parse() трактует время без смещения как локальное.',
        },
      ],
    },
  },
  {
    // Тесты: Node-API (fs, path) допустимы, а забытый `.only` молча отключает остальные тесты файла.
    files: ['src/**/__tests__/**/*.{ts,vue}', 'src/**/*.spec.ts'],
    languageOptions: { globals: { ...globals.node } },
    rules: {
      // Тела JSON-запросов и заглушки сторов в тестах: строгая типизация здесь не окупается (в src правило остаётся ошибкой).
      '@typescript-eslint/no-explicit-any': 'off',
      'no-restricted-syntax': [
        'error',
        {
          selector: "MemberExpression[property.name='only'][object.name=/^(describe|it|test)$/]",
          message: 'Забытый .only отключает остальные тесты файла.',
        },
      ],
    },
  },
  {
    files: ['*.config.{js,ts}', 'vite.config.ts', 'vitest.config.ts'],
    languageOptions: { globals: { ...globals.node } },
  },

  {
    // E2E-проверки Playwright и запуск backend для них выполняются в Node; тела page.evaluate() — уже в браузере (document, window).
    files: ['playwright.config.ts', 'e2e/**/*.{ts,mjs}'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },

  // Последним: отключает правила, конфликтующие с Prettier.
  prettier,
])
