import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { completeLogin, OidcError, startLogin, type OidcErrorCode } from '../auth/oidc'
import { Alert, Layout } from '../components/Layout'
import { OIDC_ERRORS } from '../messages'

/** /callback — where /authorize sends the browser back with `?code=…&state=…` (or `?error=…`). */
export default function Callback() {
  const navigate = useNavigate()
  // Read once, before the address bar is cleaned below
  const [search] = useState(() => window.location.search)
  const [error, setError] = useState<OidcErrorCode | null>(null)

  useEffect(() => {
    // The code is single-use and lives 60 s, but it has nothing to do in the history either
    navigate('/callback', { replace: true })
    completeLogin(search).then(
      () => navigate('/', { replace: true }),
      (e: unknown) => setError(e instanceof OidcError ? e.code : 'network'),
    )
  }, [navigate, search])

  if (error) {
    return (
      <Layout title="Connexion impossible">
        <Alert>{OIDC_ERRORS[error]}</Alert>
        <div className="actions">
          <button type="button" className="button" onClick={() => void startLogin()}>
            Recommencer la connexion
          </button>
          <Link to="/">Retour à l'accueil</Link>
        </div>
      </Layout>
    )
  }

  return (
    <Layout title="Connexion en cours">
      <p role="status">Vérification de votre connexion…</p>
    </Layout>
  )
}
