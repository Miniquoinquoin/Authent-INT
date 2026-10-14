import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { leaveTo } from '../lib/navigation'
import { mockJwt } from '../mocks/encoding'
import { server } from '../mocks/node'
import { beginLogin, callbackSearch } from '../test/oidc'
import { completeLogin, logout, OidcError } from './oidc'
import { challengeS256 } from './pkce'
import { getSession } from './session'

vi.mock('../lib/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/navigation')>()),
  leaveTo: vi.fn(),
}))

const AUTH = 'https://auth.authentint.test'

async function codeOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise
  } catch (e) {
    if (e instanceof OidcError) return e.code
    throw e
  }
  return 'resolved'
}

/** Records whether /token was called, then lets the mock answer. */
function watchToken(): { called: boolean } {
  const seen = { called: false }
  server.events.on('request:start', ({ request }) => {
    if (request.url === `${AUTH}/token`) seen.called = true
  })
  return seen
}

beforeEach(() => vi.mocked(leaveTo).mockClear())
afterEach(() => server.events.removeAllListeners())

describe('startLogin', () => {
  it('redirects to /authorize with PKCE S256, state and nonce', async () => {
    const params = await beginLogin()
    expect(vi.mocked(leaveTo).mock.lastCall?.[0]).toMatch(new RegExp(`^${AUTH}/authorize\\?`))
    expect(params.get('response_type')).toBe('code')
    expect(params.get('client_id')).toBe('portail-web')
    expect(params.get('redirect_uri')).toBe(`${window.location.origin}/callback`)
    expect(params.get('scope')!.split(' ')).toContain('openid')
    expect(params.get('code_challenge_method')).toBe('S256')
    expect(params.get('state')).toMatch(/^[A-Za-z0-9\-_]{43}$/)
    expect(params.get('nonce')).toMatch(/^[A-Za-z0-9\-_]{43}$/)
    expect(params.get('state')).not.toBe(params.get('nonce'))
    expect(params.has('code_verifier')).toBe(false) // only its hash leaves the tab

    const pending = JSON.parse(sessionStorage.getItem('authentint.oidc.pending')!)
    expect(pending.state).toBe(params.get('state'))
    expect(pending.nonce).toBe(params.get('nonce'))
    await expect(challengeS256(pending.verifier)).resolves.toBe(params.get('code_challenge'))
  })
})

describe('completeLogin', () => {
  it('exchanges the code with the verifier and keeps the tokens', async () => {
    const authorize = await beginLogin()
    const session = await completeLogin(callbackSearch(authorize))
    expect(session.user.name).toBe('Marie Dupont')
    expect(session.scopes).toEqual(['openid', 'svc:impots.read', 'svc:impots.write', 'svc:cadastre.read'])
    expect(getSession()).toBe(session)
    expect(sessionStorage.getItem('authentint.oidc.pending')).toBeNull() // single use
  })

  it('rejects a state it did not send, without calling /token', async () => {
    const watch = watchToken()
    const authorize = await beginLogin()
    expect(await codeOf(completeLogin(callbackSearch(authorize, { state: 'forged-state' })))).toBe('state_mismatch')
    expect(watch.called).toBe(false)
    expect(getSession()).toBeNull()
  })

  it('rejects a callback when no login was started in this tab', async () => {
    const authorize = await beginLogin()
    const search = callbackSearch(authorize)
    sessionStorage.clear()
    expect(await codeOf(completeLogin(search))).toBe('state_mismatch')
  })

  it('rejects an ID token minted for another nonce', async () => {
    const authorize = await beginLogin()
    expect(await codeOf(completeLogin(callbackSearch(authorize, { nonce: 'someone-elses-nonce' })))).toBe('nonce_mismatch')
    expect(getSession()).toBeNull()
  })

  it('rejects an ID token from another issuer or for another audience', async () => {
    const now = Math.floor(Date.now() / 1000)
    for (const claims of [{ iss: 'https://evil.example', aud: 'portail-web' }, { iss: AUTH, aud: 'another-app' }]) {
      const authorize = await beginLogin()
      server.use(
        http.post(`${AUTH}/token`, () =>
          HttpResponse.json({
            access_token: mockJwt({ scope: 'openid' }),
            id_token: mockJwt({ ...claims, nonce: authorize.get('nonce'), exp: now + 300 }),
            token_type: 'Bearer',
            expires_in: 600,
          }),
        ),
      )
      expect(await codeOf(completeLogin(callbackSearch(authorize)))).toBe('invalid_id_token')
    }
  })

  it('reports a refused consent, once the state is checked', async () => {
    const authorize = await beginLogin()
    const search = `?error=access_denied&state=${authorize.get('state')}`
    expect(await codeOf(completeLogin(search))).toBe('access_denied')
  })

  it('never echoes an unknown error= value', async () => {
    const authorize = await beginLogin()
    expect(await codeOf(completeLogin(`?error=%3Cscript%3E&state=${authorize.get('state')}`))).toBe('server_error')
  })

  it('fails when /token refuses the code', async () => {
    const authorize = await beginLogin()
    server.use(http.post(`${AUTH}/token`, () => HttpResponse.json({ error: 'invalid_grant' }, { status: 400 })))
    expect(await codeOf(completeLogin(callbackSearch(authorize)))).toBe('token_exchange_failed')
  })

  it('posts the verifier that matches the challenge sent to /authorize', async () => {
    let form: URLSearchParams | undefined
    server.events.on('request:start', async ({ request }) => {
      if (request.url === `${AUTH}/token`) form = new URLSearchParams(await request.clone().text())
    })
    const authorize = await beginLogin()
    await completeLogin(callbackSearch(authorize))
    expect(form?.get('grant_type')).toBe('authorization_code')
    expect(form?.get('client_id')).toBe('portail-web')
    expect(form?.get('redirect_uri')).toBe(authorize.get('redirect_uri'))
    await expect(challengeS256(form!.get('code_verifier')!)).resolves.toBe(authorize.get('code_challenge'))
  })

  it('never writes a token to localStorage or sessionStorage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem') // records, and still writes
    try {
      const authorize = await beginLogin()
      const session = await completeLogin(callbackSearch(authorize))

      expect(setItem).toHaveBeenCalled() // the pending state/nonce/verifier, and only that
      for (const [key, value] of setItem.mock.calls) {
        expect(key).toBe('authentint.oidc.pending')
        expect(value).not.toContain(session.accessToken)
        expect(value).not.toContain(session.idToken)
      }
      for (const storage of [localStorage, sessionStorage]) {
        for (let i = 0; i < storage.length; i++) {
          const value = storage.getItem(storage.key(i)!)!
          expect(value).not.toContain(session.accessToken)
          expect(value).not.toContain(session.idToken)
        }
      }
      expect(localStorage.length).toBe(0)
    } finally {
      vi.restoreAllMocks()
    }
  })
})

describe('logout', () => {
  it('forgets the tokens and goes to end-session without putting the ID token in the URL', async () => {
    const authorize = await beginLogin()
    const session = await completeLogin(callbackSearch(authorize))
    logout()
    expect(getSession()).toBeNull()
    const url = new URL(vi.mocked(leaveTo).mock.lastCall![0])
    expect(`${url.origin}${url.pathname}`).toBe(`${AUTH}/end-session`)
    expect(url.searchParams.get('client_id')).toBe('portail-web')
    expect(url.searchParams.get('post_logout_redirect_uri')).toBe(`${window.location.origin}/`)
    expect(url.href).not.toContain(session.idToken)
  })
})
