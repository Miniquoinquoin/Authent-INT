/**
 * PKCE (RFC 7636), by hand: it's ten lines and it's the point of the project.
 *
 * The portal is a public client: it has no secret. What proves that the browser exchanging
 * the code at /token is the one that started the flow is `code_verifier`, a random string
 * that never leaves this tab until that exchange. /authorize only ever sees its SHA-256.
 */

/** base64url without padding (RFC 4648 §5), the encoding RFC 7636 asks for. */
export function base64url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * 32 bytes from the CSPRNG → 43 characters of [A-Za-z0-9-_]: 256 bits of entropy.
 * Used for code_verifier (RFC 7636 §4.1: 43 to 128 unreserved characters), state and nonce.
 */
export function randomToken(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(32)))
}

/** code_challenge = BASE64URL(SHA256(ASCII(code_verifier))) — the S256 method, the only one the server accepts. */
export async function challengeS256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64url(new Uint8Array(digest))
}
