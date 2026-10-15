/**
 * The fake auth-server of lane B5 (ADR §17: "Démarre contre: Mock OpenAPI (MSW)").
 * Response shapes are typed from the generated OpenAPI (src/api/types.ts): if the
 * contract changes, the mock stops compiling instead of silently lying.
 *
 * Same handlers in Vitest (msw/node, ./node.ts) and in the browser (`npm run dev:mock`, ./browser.ts).
 */
import { accountHandlers } from './account'
import { interactionHandlers, resetInteractionMock } from './interaction'
import { oidcHandlers, resetOidcMock } from './oidc'
import { serviceHandlers } from './services'

export const handlers = [...interactionHandlers, ...accountHandlers, ...oidcHandlers, ...serviceHandlers]

/** Forget used codes, logged-in interactions...: one test must not see the previous one's state. */
export function resetMocks(): void {
  resetInteractionMock()
  resetOidcMock()
}
