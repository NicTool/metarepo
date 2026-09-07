import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  workers: 1,
  use: { baseURL: 'http://server:8080' },
})
