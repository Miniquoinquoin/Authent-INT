/**
 * The mock keeps no server: what the real auth-server stores in `interactions` and
 * `authorization_codes`, the mock packs into the opaque handles themselves (uid, code).
 * The SPA never looks inside them — exactly as with the real server.
 */
import { base64url } from '../auth/pkce'

export interface MockInteraction {
  client_id: string
  redirect_uri: string
  scope: string
  state: string
  nonce: string
  code_challenge: string
}

export interface MockCode {
  sub: string
  client_id: string
  redirect_uri: string
  scope: string
  nonce: string
  code_challenge: string
}

export function pack(value: object): string {
  return base64url(new TextEncoder().encode(JSON.stringify(value)))
}

export function unpack<T>(handle: string): T | null {
  try {
    const base64 = handle.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(handle.length / 4) * 4, '=')
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)))) as T
  } catch {
    return null
  }
}

/** An unsigned look-alike of the server's RS256 JWTs: the SPA only reads payloads. */
export function mockJwt(payload: object, typ = 'JWT'): string {
  return `${pack({ alg: 'RS256', typ, kid: 'mock' })}.${pack(payload)}.bW9jay1zaWduYXR1cmU`
}
