import { defineConfig } from 'vitest/config'

// UI tests only (*.spec.*); the pure-function tests run with `node --test` (see package.json).
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.{js,jsx}'],
    restoreMocks: true,
  },
})
