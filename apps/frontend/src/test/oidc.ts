/**
 * Plays the auth-server's /authorize for the tests: starts a login the way the SPA does,
 * then builds the `?code=…&state=…` the server would send to /callback.
 * Requires `vi.mock('../lib/navigation', ...)` in the calling test file (leaveTo is a spy).
 */
import { expect, vi } from 'vitest'
import { startLogin } from '../auth/oidc'
import { leaveTo } from '../lib/navigation'
import { grant, MOCK_USERS } from '../mocks/data'
import { issueCode } from '../mocks/oidc'

export async function beginLogin(): Promise<URLSearchParams> {
  await startLogin()
  const url = vi.mocked(leaveTo).mock.lastCall?.[0]
  expect(url).toBeDefined()
  return new URL(url as string).searchParams
}

export function callbackSearch(
  authorize: URLSearchParams,
  overrides: { numero?: string; nonce?: string; state?: string } = {},
): string {
  const user = MOCK_USERS[overrides.numero ?? '1234567890123']
  const code = issueCode({
    sub: user.sub,
    client_id: authorize.get('client_id')!,
    redirect_uri: authorize.get('redirect_uri')!,
    scope: grant(authorize.get('scope')!.split(' '), user.role).join(' '),
    nonce: overrides.nonce ?? authorize.get('nonce')!,
    code_challenge: authorize.get('code_challenge')!,
  })
  return `?${new URLSearchParams({ code, state: overrides.state ?? authorize.get('state')! })}`
}
