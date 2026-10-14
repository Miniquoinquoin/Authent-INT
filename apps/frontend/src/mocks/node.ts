/** MSW for Vitest: the same handlers as the browser mock, intercepted in Node. */
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
