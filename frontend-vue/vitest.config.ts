import { defineConfig, mergeConfig } from 'vite'
import { defineConfig as defineVitestConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineVitestConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      css: false,
      // Стабы vi.stubGlobal (fetch, confirm и т.п.) не должны переживать границу
      // теста по умолчанию — иначе тест может случайно пройти на стабе, оставшемся
      // от предыдущего теста, вместо своего собственного (наступили на это в
      // DeviceFormModal.spec.ts при живой разработке).
      unstubGlobals: true,
    },
  }),
)
