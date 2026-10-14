import { useEffect, useState } from 'react'
import { CLIENT_ID, POST_LOGOUT_REDIRECT_URI, REDIRECT_URI } from '../config'
import { Alert, Layout } from '../components/Layout'
import { mockUid } from './interaction'

/**
 * Fake GET /authorize: the same checks as oidc/authorize.py in the same order (client and
 * exact redirect_uri first, then code / openid / state / nonce / S256), then the 302 to
 * /login?uid=… — with no SSO path: the mock always asks for the password.
 * Returns where to go, or null for the error page (never redirect to an unverified redirect_uri).
 */
function authorize(search: string): string | null {
  const q = new URLSearchParams(search)
  if (q.get('client_id') !== CLIENT_ID || q.get('redirect_uri') !== REDIRECT_URI) return null
  const ok =
    q.get('response_type') === 'code' &&
    (q.get('scope') ?? '').split(' ').includes('openid') &&
    !!q.get('state') &&
    !!q.get('nonce') &&
    !!q.get('code_challenge') &&
    q.get('code_challenge_method') === 'S256'
  if (!ok) return `${REDIRECT_URI}?${new URLSearchParams({ error: 'invalid_request', state: q.get('state') ?? '' })}`
  const uid = mockUid({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: q.get('scope')!,
    state: q.get('state')!,
    nonce: q.get('nonce')!,
    code_challenge: q.get('code_challenge')!,
  })
  return `/login?uid=${uid}`
}

export function MockAuthorize() {
  const [target] = useState(() => authorize(window.location.search))
  useEffect(() => {
    if (target) window.location.replace(target) // a 302, as the real server does
  }, [target])

  return (
    <Layout title="Serveur d'authentification simulé">
      {target ? <p role="status">Redirection…</p> : <Alert>Requête d'autorisation invalide.</Alert>}
    </Layout>
  )
}

/** Fake GET /end-session: back to the registered post-logout URI. */
export function MockEndSession() {
  useEffect(() => {
    const target = new URLSearchParams(window.location.search).get('post_logout_redirect_uri')
    window.location.replace(target === POST_LOGOUT_REDIRECT_URI ? target : '/')
  }, [])
  return (
    <Layout title="Serveur d'authentification simulé">
      <p role="status">Déconnexion…</p>
    </Layout>
  )
}
