/**
 * The portal as an OIDC Relying Party: the public client `portail-web`, authorization code
 * flow with PKCE S256, `state` and `nonce` (ADR §10).
 *
 * This is the ONLY module that knows B2's endpoints (/authorize, /token, /end-session).
 * Until B2 merges they are mocked (src/mocks/); at seam S2/S3 the mock goes and, if B2's
 * shapes moved, this file and claims.ts are what change.
 */
import { AUTH_URL, CLIENT_ID, ISSUER, POST_LOGOUT_REDIRECT_URI, REDIRECT_URI, SCOPES } from '../config'
import { leaveTo } from '../lib/navigation'
import { decodePayload, type AccessTokenClaims, type IdTokenClaims, type TokenResponse } from './claims'
import { challengeS256, randomToken } from './pkce'
import { setSession, type Session } from './session'

/** RFC 6749 §4.1.2.1: what /authorize may send back in `error=` (domain/errors.py AuthorizeErrorCode). */
const AUTHORIZE_ERRORS = [
  'invalid_request',
  'unauthorized_client',
  'access_denied',
  'unsupported_response_type',
  'invalid_scope',
  'server_error',
  'temporarily_unavailable',
] as const
type AuthorizeErrorCode = (typeof AUTHORIZE_ERRORS)[number]

export type OidcErrorCode =
  | AuthorizeErrorCode
  | 'state_mismatch' // the answer doesn't belong to a login this tab started: CSRF, or a stale tab
  | 'nonce_mismatch' // the ID token wasn't minted for this login: replay
  | 'invalid_id_token' // wrong iss / aud / expired / unreadable
  | 'missing_code'
  | 'token_exchange_failed' // /token said no (invalid_grant: code used, expired, PKCE mismatch...)
  | 'network'

export class OidcError extends Error {
  readonly code: OidcErrorCode
  constructor(code: OidcErrorCode) {
    super(code)
    this.name = 'OidcError'
    this.code = code
  }
}

/**
 * What must survive the round trip to the auth-server, and nothing else. sessionStorage:
 * scoped to this tab, gone when it closes, and read exactly once by the callback.
 */
const PENDING_KEY = 'authentint.oidc.pending'
interface Pending {
  state: string
  nonce: string
  verifier: string
}

export function authorizeUrl(params: { state: string; nonce: string; challenge: string }): string {
  const query = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: SCOPES.join(' '),
    state: params.state,
    nonce: params.nonce,
    code_challenge: params.challenge,
    code_challenge_method: 'S256',
  })
  return `${AUTH_URL}/authorize?${query}`
}

/** "Se connecter": fresh verifier/state/nonce, then off to /authorize. */
export async function startLogin(): Promise<void> {
  const pending: Pending = { state: randomToken(), nonce: randomToken(), verifier: randomToken() }
  const challenge = await challengeS256(pending.verifier)
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending))
  leaveTo(authorizeUrl({ state: pending.state, nonce: pending.nonce, challenge }))
}

function takePending(): Pending | null {
  const raw = sessionStorage.getItem(PENDING_KEY)
  sessionStorage.removeItem(PENDING_KEY) // single use, whatever happens next
  if (!raw) return null
  try {
    return JSON.parse(raw) as Pending
  } catch {
    return null
  }
}

async function exchange(code: string, verifier: string): Promise<TokenResponse> {
  let response: Response
  try {
    response = await fetch(`${AUTH_URL}/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: REDIRECT_URI,
        client_id: CLIENT_ID, // public client: no secret, PKCE is the proof
        code_verifier: verifier,
      }),
      credentials: 'omit', // /token authenticates the code + verifier, not a cookie
    })
  } catch {
    throw new OidcError('network')
  }
  if (!response.ok) throw new OidcError('token_exchange_failed')
  return (await response.json()) as TokenResponse
}

/** OIDC Core §3.1.3.7: the checks a client must make on an ID token from the token endpoint. */
function checkIdToken(idToken: string, nonce: string): IdTokenClaims {
  let claims: IdTokenClaims
  try {
    claims = decodePayload<IdTokenClaims>(idToken)
  } catch {
    throw new OidcError('invalid_id_token')
  }
  const audience = Array.isArray(claims.aud) ? claims.aud : [claims.aud]
  if (claims.iss !== ISSUER || !audience.includes(CLIENT_ID)) throw new OidcError('invalid_id_token')
  if (typeof claims.exp !== 'number' || claims.exp * 1000 < Date.now() - 60_000) throw new OidcError('invalid_id_token')
  if (claims.nonce !== nonce) throw new OidcError('nonce_mismatch')
  return claims
}

async function complete(search: string): Promise<Session> {
  const params = new URLSearchParams(search)
  const pending = takePending()
  const state = params.get('state')
  // First, before reading anything else: an answer to a request we didn't make is dropped
  if (!pending || !state || state !== pending.state) throw new OidcError('state_mismatch')

  const error = params.get('error')
  if (error) {
    throw new OidcError((AUTHORIZE_ERRORS as readonly string[]).includes(error) ? (error as AuthorizeErrorCode) : 'server_error')
  }
  const code = params.get('code')
  if (!code) throw new OidcError('missing_code')

  const tokens = await exchange(code, pending.verifier)
  if (!tokens.access_token || !tokens.id_token || tokens.token_type?.toLowerCase() !== 'bearer') {
    throw new OidcError('token_exchange_failed')
  }
  const user = checkIdToken(tokens.id_token, pending.nonce)

  // RFC 6749 §5.1: `scope` in the answer is what was GRANTED; B2 always sends it
  let scope = tokens.scope
  if (scope === undefined) {
    try {
      scope = decodePayload<AccessTokenClaims>(tokens.access_token).scope
    } catch {
      scope = ''
    }
  }

  const session: Session = {
    accessToken: tokens.access_token,
    idToken: tokens.id_token,
    user,
    scopes: scope.split(' ').filter(Boolean),
    expiresAt: Date.now() + tokens.expires_in * 1000,
  }
  setSession(session) // memory only, see session.ts
  return session
}

// React StrictMode runs effects twice in dev: the second run must not spend the code again
const inflight = new Map<string, Promise<Session>>()

/** /callback: `search` is location.search as the auth-server sent it (`?code=…&state=…` or `?error=…&state=…`). */
export function completeLogin(search: string): Promise<Session> {
  let promise = inflight.get(search)
  if (!promise) {
    promise = complete(search)
    inflight.set(search, promise)
  }
  return promise
}

/**
 * "Se déconnecter": forget the tokens here, then RP-initiated logout at the OP so the
 * __Host-session cookie dies too (otherwise the next "Se connecter" is silently SSO'd back in).
 *
 * No `id_token_hint`: it would put a JWT carrying the user's name into a URL — browser history
 * and the edge's access logs. `client_id` + the browser's session cookie identify the session.
 * To agree with B2 (open question in the PR).
 */
export function logout(): void {
  setSession(null)
  const query = new URLSearchParams({ client_id: CLIENT_ID, post_logout_redirect_uri: POST_LOGOUT_REDIRECT_URI })
  leaveTo(`${AUTH_URL}/end-session?${query}`)
}
