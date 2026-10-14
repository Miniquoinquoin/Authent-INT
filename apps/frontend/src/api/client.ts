/**
 * The one place that talks HTTP to the auth-server's own API (interaction + account).
 *
 * - `credentials: "include"`: the login answer sets the HttpOnly `__Host-session` cookie on
 *   the auth origin; without it the browser drops the cookie and SSO never happens.
 * - Errors become an `ApiError` carrying a code from a closed list: screens map that code to a
 *   French message of OUR choosing, they never display what the server (or a URL) said.
 * - Nothing here logs: request bodies carry the numero fiscal and passwords.
 *
 * The OIDC endpoints (/token, /end-session) are not here: they belong to B2 and live in
 * src/auth/oidc.ts, so seam S2/S3 touches one file.
 */
import { AUTH_URL } from '../config'
import type { components, paths } from './types'

export type Schemas = components['schemas']

/** Codes the server sends in `{"detail": "..."}` (apps/auth-server/src/authentint/flows/*.py). */
const SERVER_CODES = [
  'invalid_credentials', // 401 login: bad numero fiscal OR bad password, same answer for both
  'account_locked', // 423 login: 5 failures
  'too_many_attempts', // 429 login / request endpoints: per-IP rate limit
  'unknown_interaction', // 404: unknown or expired uid (TTL 10 min)
  'login_required', // 400 consent before login
  'invalid_token', // 400 activation/reset confirm: unknown, expired or used link
] as const

export type ServerErrorCode = (typeof SERVER_CODES)[number]
/** `validation`: 422. `network`: no answer at all. `unexpected`: anything else (5xx...). */
export type ApiErrorCode = ServerErrorCode | 'validation' | 'network' | 'unexpected'

export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly status: number

  constructor(code: ApiErrorCode, status: number) {
    super(code) // the code only: never a server-provided sentence
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

// When the body has no recognised `detail` (a proxy's error page, say), the status still tells
const BY_STATUS: Record<number, ApiErrorCode> = {
  401: 'invalid_credentials',
  404: 'unknown_interaction',
  422: 'validation',
  423: 'account_locked',
  429: 'too_many_attempts',
}

function isServerCode(value: unknown): value is ServerErrorCode {
  return typeof value === 'string' && (SERVER_CODES as readonly string[]).includes(value)
}

async function toError(response: Response): Promise<ApiError> {
  let detail: unknown
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    detail = undefined
  }
  if (response.status === 422) return new ApiError('validation', 422) // detail is a list there
  if (isServerCode(detail)) return new ApiError(detail, response.status)
  return new ApiError(BY_STATUS[response.status] ?? 'unexpected', response.status)
}

/**
 * Builds a URL from a path template of the generated contract: `"/interaction/{uid}"` must exist
 * in docs/generated/openapi.json or this doesn't compile. Parameters are URI-encoded.
 */
export function apiUrl<P extends keyof paths>(template: P, params: Record<string, string> = {}): string {
  const path = (template as string).replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name]
    if (value === undefined) throw new Error(`missing path parameter ${name}`)
    return encodeURIComponent(value)
  })
  return `${AUTH_URL}${path}`
}

export async function call<T>(method: 'GET' | 'POST', url: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      method,
      credentials: 'include',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('network', 0)
  }
  if (!response.ok) throw await toError(response)
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError('unexpected', response.status)
  }
}
