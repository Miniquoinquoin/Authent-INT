import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { confirmActivation, confirmPasswordReset } from '../../api/account'
import { ApiError } from '../../api/client'
import { startLogin } from '../../auth/oidc'
import { Alert, Layout, Notice } from '../../components/Layout'
import { API_ERRORS } from '../../messages'

const MIN = 12 // ANSSI: length, not composition rules — the server enforces the same (flows/activation.py)
const MAX = 256

const TEXT = {
  activation: {
    title: 'Choisir mon mot de passe',
    done: 'Votre compte est activé. Vous pouvez maintenant vous connecter.',
    again: { to: '/activation', label: "Demander un nouveau lien d'activation" },
    send: confirmActivation,
  },
  reset: {
    title: 'Nouveau mot de passe',
    done: 'Votre mot de passe a été modifié. Par sécurité, toutes vos sessions ouvertes ont été fermées.',
    again: { to: '/mot-de-passe-oublie', label: 'Demander un nouveau lien' },
    send: confirmPasswordReset,
  },
}

/** /activate?token=… and /reset-password?token=…: the link from the e-mail. */
export function ChoosePassword({ kind }: { kind: 'activation' | 'reset' }) {
  const text = TEXT[kind]
  const [params] = useSearchParams()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  // Read once; the address bar is cleaned right after (effect below)
  const [token] = useState(() => params.get('token'))
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(token ? null : API_ERRORS.invalid_token)
  const [tokenDead, setTokenDead] = useState(!token)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    // The link is a bearer credential until used: keep it out of the history and of any Referer
    if (params.has('token')) navigate(pathname, { replace: true })
  }, [params, pathname, navigate])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (password.length < MIN || password.length > MAX) {
      setError(`Le mot de passe doit comporter au moins ${MIN} caractères.`)
      return
    }
    if (password !== confirmation) {
      setError('Les deux mots de passe ne sont pas identiques.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await text.send({ token: token!, password })
      setPassword('')
      setConfirmation('')
      setDone(true)
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unexpected'
      if (code === 'invalid_token') setTokenDead(true)
      setError(API_ERRORS[code])
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <Layout title={text.title}>
        <Notice>{text.done}</Notice>
        <div className="actions">
          <button type="button" className="button" onClick={() => void startLogin()}>
            Se connecter
          </button>
        </div>
      </Layout>
    )
  }

  if (tokenDead) {
    return (
      <Layout title={text.title}>
        <Alert>{error}</Alert>
        <p>
          <Link to={text.again.to}>{text.again.label}</Link>
        </p>
      </Layout>
    )
  }

  return (
    <Layout title={text.title}>
      <form method="post" noValidate onSubmit={submit} className="form">
        <div className="field">
          <label htmlFor="nouveau-mot-de-passe">Mot de passe</label>
          <p id="mot-de-passe-aide" className="hint">
            Au moins {MIN} caractères. Une phrase facile à retenir convient très bien.
          </p>
          <input
            id="nouveau-mot-de-passe"
            type="password"
            autoComplete="new-password"
            maxLength={MAX}
            aria-describedby="mot-de-passe-aide"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="confirmation-mot-de-passe">Confirmez le mot de passe</label>
          <input
            id="confirmation-mot-de-passe"
            type="password"
            autoComplete="new-password"
            maxLength={MAX}
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
          />
        </div>
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="button" disabled={busy}>
          {busy ? 'Enregistrement…' : 'Enregistrer le mot de passe'}
        </button>
      </form>
    </Layout>
  )
}
