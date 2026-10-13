import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  workers: 1,
  use: { baseURL: process.env.NICTOOL_V3_URL },
})
