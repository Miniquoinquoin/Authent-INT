/**
 * Mock mode in the browser (`npm run dev:mock`, used by Playwright): MSW's service worker
 * answers the API calls, and two routes stand in for the auth-server's browser-facing
 * redirects. A service worker can't fake those — MSW deliberately lets page navigations
 * through — so the fake /authorize and /end-session are tiny SPA routes. Only loaded when
 * `import.meta.env.MODE === 'mock'` (see main.tsx): a normal build doesn't contain this file.
 */
import { setupWorker } from 'msw/browser'
import { Route } from 'react-router'
import { MockAuthorize, MockEndSession } from './MockAuthorize'
import { handlers } from './handlers'

export async function startMockWorker(): Promise<void> {
  await setupWorker(...handlers).start({
    quiet: true, // MSW logs every request body to the console otherwise: numero fiscal, passwords
    onUnhandledRequest: 'bypass',
    serviceWorker: { url: '/mockServiceWorker.js' },
  })
}

export const mockRoutes = (
  <>
    <Route path="/mock-auth/authorize" element={<MockAuthorize />} />
    <Route path="/mock-auth/end-session" element={<MockEndSession />} />
  </>
)
