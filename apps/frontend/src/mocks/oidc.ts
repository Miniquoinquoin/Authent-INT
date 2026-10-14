/**
 * Fake of B2's /token (apps/auth-server/src/authentint/oidc/token.py):
 * form-encoded body, `{"error": ...}` 400s, the same response fields, and the same checks
 * that matter to the SPA — single-use code, client_id + redirect_uri bound, PKCE S256.
 * The real one is on main since B2 merged; this fake stays for Vitest and `npm run dev:mock`.
 */
import { http, HttpResponse } from 'msw'
import { challengeS256 } from '../auth/pkce'
import type { AccessTokenClaims, IdTokenClaims, TokenResponse } from '../auth/claims'
import { AUTH_URL } from '../config'
import { audiences, MOCK_USERS } from './data'
import { mockJwt, pack, unpack, type MockCode } from './encoding'

const usedCodes = new Set<string>()

export function resetOidcMock(): void {
  usedCodes.clear()
}

export function issueCode(code: MockCode): string {
  return pack(code)
}

function invalid(error: string) {
  return HttpResponse.json({ error }, { status: 400, headers: { 'Cache-Control': 'no-store' } })
}

export const oidcHandlers = [
  http.post(`${AUTH_URL}/token`, async ({ request }) => {
    const form = new URLSearchParams(await request.text())
    if (form.get('grant_type') !== 'authorization_code') return invalid('unsupported_grant_type')
    const raw = form.get('code') ?? ''
    const verifier = form.get('code_verifier') ?? ''
    if (verifier.length < 43 || verifier.length > 128) return invalid('invalid_request')

    const code = unpack<MockCode>(raw)
    if (!code || usedCodes.has(raw)) return invalid('invalid_grant')
    usedCodes.add(raw)
    if (form.get('client_id') !== code.client_id || form.get('redirect_uri') !== code.redirect_uri) return invalid('invalid_grant')
    if ((await challengeS256(verifier)) !== code.code_challenge) return invalid('invalid_grant')

    const user = Object.values(MOCK_USERS).find((u) => u.sub === code.sub)
    if (!user) return invalid('invalid_grant')

    const now = Math.floor(Date.now() / 1000)
    const sid = '9e1f2a3b-4c5d-4e6f-8a7b-9c0d1e2f3a4b'
    const scopes = code.scope.split(' ')
    const id: IdTokenClaims = {
      iss: AUTH_URL, sub: user.sub, aud: code.client_id, exp: now + 300, iat: now, auth_time: now, nonce: code.nonce,
      acr: 'urn:authentint:acr:pwd', amr: ['pwd'], sid, name: `${user.given_name} ${user.family_name}`,
      given_name: user.given_name, family_name: user.family_name, role: user.role,
    }
    const access: AccessTokenClaims = {
      iss: AUTH_URL, sub: user.sub, aud: audiences(scopes), client_id: code.client_id, scope: code.scope,
      exp: now + 600, iat: now, jti: crypto.randomUUID(), sid, acr: 'urn:authentint:acr:pwd',
    }
    const body: TokenResponse = {
      access_token: mockJwt(access, 'at+jwt'), id_token: mockJwt(id), token_type: 'Bearer', expires_in: 600, scope: code.scope,
    }
    return HttpResponse.json(body, { headers: { 'Cache-Control': 'no-store' } })
  }),
]
