/**
 * Token shapes, mirrored from the frozen B0 contract (ADR §7, current_architecture.md §6):
 * apps/auth-server/src/authentint/domain/claims.py (IdToken, AccessToken) and the /token
 * response of B2 (oidc/token.py on feat/b2-oidc). /token is not in the OpenAPI export, hence
 * the hand-written types: change them in the same PR as claims.py.
 */

export type Role = 'admin' | 'agent' | 'contribuable'

export interface IdTokenClaims {
  iss: string
  sub: string
  aud: string
  exp: number
  iat: number
  auth_time: number
  nonce: string
  acr: string
  amr: string[]
  sid: string
  name: string
  given_name: string
  family_name: string
  role: Role
}

export interface AccessTokenClaims {
  iss: string
  sub: string
  aud: string[]
  client_id: string
  scope: string
  exp: number
  iat: number
  jti: string
  sid: string
  acr: string
}

/** RFC 6749 §5.1, as B2 answers it. `refresh_token` only with `offline_access`, which the portal doesn't ask. */
export interface TokenResponse {
  access_token: string
  id_token: string
  token_type: 'Bearer'
  expires_in: number
  scope?: string
  refresh_token?: string
}

/**
 * Reads a JWT's payload WITHOUT verifying its signature. Fine for what the SPA does with it:
 * - the ID token came straight from the token endpoint over TLS, which OIDC Core §3.1.3.7
 *   (step 6) accepts in place of a signature check for this flow;
 * - the access token is opaque to the portal: the Resource Servers verify it against JWKS.
 * Never use this to make an authorisation decision.
 */
export function decodePayload<T>(jwt: string): T {
  const part = jwt.split('.')[1]
  if (!part) throw new Error('not a JWT')
  const base64 = part.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(part.length / 4) * 4, '=')
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  return JSON.parse(new TextDecoder().decode(bytes)) as T
}
