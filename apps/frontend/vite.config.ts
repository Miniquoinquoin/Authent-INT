/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The auth-server as the tests see it: MSW (msw/node) answers on this origin
    env: { VITE_AUTH_URL: 'https://auth.authentint.test' },
  },
})
