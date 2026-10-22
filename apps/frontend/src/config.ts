/**
 * Every URL and OIDC parameter the SPA uses, in one place.
 *
 * Values are baked in at build time by Vite (`VITE_*`), so the same image can't be
 * pointed at another server by tampering with the page: changing them is a rebuild.
 */

function absolute(raw: string): string {
  // A relative value (the mock mode uses "/mock-auth") is resolved against the SPA's own origin.
  // No normalisation beyond that: redirect URIs are compared as exact strings by the server.
  return new URL(raw, window.location.origin).href
}

const rawAuthUrl = import.meta.env.VITE_AUTH_URL as string | undefined
if (!rawAuthUrl) {
  throw new Error("VITE_AUTH_URL n'est pas défini : voir apps/frontend/.env.example")
}

/** The auth-server. It is also the OIDC `issuer`: the ID token's `iss` must equal it. */
export const AUTH_URL = absolute(rawAuthUrl).replace(/\/+$/, '')
export const ISSUER = AUTH_URL

/** The portal is the public OAuth client `portail-web` (apps/auth-server/scripts/seed.py). */
export const CLIENT_ID = 'portail-web'

/**
 * Must be byte-for-byte one of the client's registered `redirect_uris` (ADR §10 step 2).
 * Default: this origin + /callback, which is right for every environment where the
 * SPA is served on the registered host (https://app.authentint.localhost in dev).
 */
export const REDIRECT_URI = absolute(
  (import.meta.env.VITE_OIDC_REDIRECT_URI as string | undefined) ?? '/callback',
)

/** The Resource Servers the portal calls with the access token (ADR §11). */
export const IMPOTS_URL = absolute(
  (import.meta.env.VITE_IMPOTS_URL as string | undefined) ?? 'https://app.authentint.localhost/api/impots',
).replace(/\/+$/, '')
export const CADASTRE_URL = absolute(
  (import.meta.env.VITE_CADASTRE_URL as string | undefined) ?? 'https://app.authentint.localhost/api/cadastre',
).replace(/\/+$/, '')

export const POST_LOGOUT_REDIRECT_URI = absolute(
  (import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI as string | undefined) ?? '/',
)

/**
 * What the portal ASKS for. The server grants `requested ∩ allowed(role) ∩ client.allowed_scopes`
 * (ADR §7): a contribuable asking for svc:impots.write simply doesn't get it.
 * Admin scopes join this list with the admin screens (B4).
 */
export const SCOPES = ['openid', 'svc:impots.read', 'svc:impots.write', 'svc:cadastre.read']
