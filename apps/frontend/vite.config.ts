/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

/**
 * `vite --mode mock` (npm run dev:mock): the SPA runs against MSW in the browser instead of a
 * real auth-server. The service worker script is served from node_modules rather than
 * committed to public/, so it never ships in a real build and can't drift from the msw version.
 */
function mswWorker(): Plugin {
  const script = createRequire(import.meta.url).resolve('msw/mockServiceWorker.js')
  return {
    name: 'authentint:msw-worker',
    configureServer(server) {
      server.middlewares.use('/mockServiceWorker.js', (_req, res) => {
        res.setHeader('Content-Type', 'text/javascript')
        res.end(readFileSync(script))
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), mode === 'mock' && mswWorker()],
  // Mock mode: the "auth-server" is this same origin under /mock-auth, so the service worker
  // sees every call (it only intercepts same-origin requests)
  define:
    mode === 'mock'
      ? {
          'import.meta.env.VITE_AUTH_URL': JSON.stringify('/mock-auth'),
          'import.meta.env.VITE_IMPOTS_URL': JSON.stringify('/mock-impots'),
          'import.meta.env.VITE_CADASTRE_URL': JSON.stringify('/mock-cadastre'),
        }
      : {},
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The auth-server as the tests see it: MSW (msw/node) answers on this origin
    env: {
      VITE_AUTH_URL: 'https://auth.authentint.test',
      VITE_IMPOTS_URL: 'https://impots.authentint.test',
      VITE_CADASTRE_URL: 'https://cadastre.authentint.test',
    },
  },
}))
