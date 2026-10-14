import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { setSession } from '../auth/session'
import { resetMocks } from '../mocks/handlers'
import { server } from '../mocks/node'

// An unmocked request is a test bug, not a pass: fail loudly
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetMocks()
  setSession(null)
  sessionStorage.clear()
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})
afterAll(() => server.close())
