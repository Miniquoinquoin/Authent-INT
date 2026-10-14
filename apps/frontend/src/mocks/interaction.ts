/**
 * Fake of the interaction API (apps/auth-server/src/authentint/flows/interaction.py): same
 * status codes, same `{"detail": code}` bodies, same order of checks, and the server alone
 * decides the next `prompt`. Two simplifications:
 * - the per-IP rate limit is triggered by a magic number (RATE_LIMITED_NUMERO);
 * - when the flow is finished, `redirect_to` is the client's callback with the code directly,
 *   where the real server first sends the browser back to /authorize (which then takes the
 *   SSO path thanks to the cookie). The SPA follows `redirect_to` either way.
 */
import { http, HttpResponse } from 'msw'
import type { ConsentBody, InteractionView, LoginBody } from '../api/interaction'
import { AUTH_URL, CLIENT_ID, REDIRECT_URI, SCOPES } from '../config'
import { grant, LOCKED_NUMERO, MOCK_PASSWORD, MOCK_USERS, RATE_LIMITED_NUMERO, type MockUser } from './data'
import { pack, unpack, type MockInteraction } from './encoding'
import { issueCode } from './oidc'

const CLIENT_NAMES: Record<string, string> = { 'portail-web': 'Portail' } // scripts/seed.py

const loggedIn = new Map<string, MockUser>()
const consented = new Set<string>()
const finished = new Set<string>()

export function resetInteractionMock(): void {
  loggedIn.clear()
  consented.clear()
  finished.clear()
}

/** A uid as /authorize would have created it. Tests use it to open /login directly. */
export function mockUid(overrides: Partial<MockInteraction> = {}): string {
  return pack({
    client_id: CLIENT_ID, redirect_uri: REDIRECT_URI, scope: SCOPES.join(' '),
    state: 'state-de-test', nonce: 'nonce-de-test', code_challenge: 'challenge-de-test', ...overrides,
  } satisfies MockInteraction)
}

function load(uid: string): MockInteraction | null {
  if (finished.has(uid)) return null
  const it = unpack<MockInteraction>(uid)
  return it && typeof it.redirect_uri === 'string' && typeof it.scope === 'string' ? it : null
}

function withQuery(uri: string, params: Record<string, string>): string {
  return `${uri}${uri.includes('?') ? '&' : '?'}${new URLSearchParams(params)}`
}

function view(uid: string, it: MockInteraction): InteractionView {
  const user = loggedIn.get(uid)
  // next_step(): no user → login; consent required (the mock client always asks) → consent; else done
  const prompt: InteractionView['prompt'] = !user ? 'login' : consented.has(uid) ? null : 'consent'
  let redirect_to: string | null = null
  if (prompt === null && user) {
    finished.add(uid) // a code is issued once per interaction
    const code = issueCode({
      sub: user.sub, client_id: it.client_id, redirect_uri: it.redirect_uri,
      scope: grant(it.scope.split(' '), user.role).join(' '), nonce: it.nonce, code_challenge: it.code_challenge,
    })
    redirect_to = withQuery(it.redirect_uri, { code, state: it.state })
  }
  return { prompt, client_name: CLIENT_NAMES[it.client_id] ?? it.client_id, scopes: it.scope.split(' '), redirect_to }
}

const detail = (code: string, status: number) => HttpResponse.json({ detail: code }, { status })
const validationError = () => HttpResponse.json({ detail: [{ loc: ['body'], msg: 'invalid', type: 'value_error' }] }, { status: 422 })

export const interactionHandlers = [
  http.get<{ uid: string }>(`${AUTH_URL}/interaction/:uid`, ({ params }) => {
    const it = load(params.uid)
    return it ? HttpResponse.json<InteractionView>(view(params.uid, it)) : detail('unknown_interaction', 404)
  }),

  http.post<{ uid: string }, LoginBody>(`${AUTH_URL}/interaction/:uid/login`, async ({ params, request }) => {
    const body = await request.json()
    if (!/^\d{13}$/.test(body?.numero_fiscal ?? '') || !body.password) return validationError()
    if (body.numero_fiscal === RATE_LIMITED_NUMERO) return detail('too_many_attempts', 429)
    const it = load(params.uid)
    if (!it) return detail('unknown_interaction', 404)
    if (body.numero_fiscal === LOCKED_NUMERO) return detail('account_locked', 423)
    const user = MOCK_USERS[body.numero_fiscal]
    if (!user || body.password !== MOCK_PASSWORD) return detail('invalid_credentials', 401)
    loggedIn.set(params.uid, user)
    return HttpResponse.json<InteractionView>(view(params.uid, it))
  }),

  http.post<{ uid: string }, ConsentBody>(`${AUTH_URL}/interaction/:uid/consent`, async ({ params, request }) => {
    const body = await request.json()
    if (typeof body?.approve !== 'boolean') return validationError()
    const it = load(params.uid)
    if (!it) return detail('unknown_interaction', 404)
    if (!loggedIn.has(params.uid)) return detail('login_required', 400)
    if (!body.approve) {
      finished.add(params.uid) // the flow is over: this uid can't be replayed
      return HttpResponse.json<InteractionView>({
        prompt: null, client_name: CLIENT_NAMES[it.client_id] ?? it.client_id, scopes: it.scope.split(' '),
        redirect_to: withQuery(it.redirect_uri, { error: 'access_denied', state: it.state }),
      })
    }
    consented.add(params.uid)
    return HttpResponse.json<InteractionView>(view(params.uid, it))
  }),
]
