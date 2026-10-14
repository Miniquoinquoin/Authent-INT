import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, type ApiErrorCode } from '../../api/client'
import { postLogin, type InteractionView } from '../../api/interaction'
import { Alert, Layout } from '../../components/Layout'
import { API_ERRORS, NUMERO_FISCAL_FORMAT } from '../../messages'

/** Errors that end this interaction: the uid is dead, only a new /authorize helps. */
const FATAL: ApiErrorCode[] = ['unknown_interaction', 'login_required']

/**
 * prompt = "login": numero fiscal + password.
 *
 * The numero fiscal is personal data (ADR §7): it stays in this component's state, goes out
 * only in the JSON body of the POST, and never into a URL, a log or Web Storage. The inputs
 * have no `name` and the form is `method="post"`: even a native submission (JS not loaded
 * yet) could never serialise it into a query string.
 */
export function LoginStep({
  uid,
  onNext,
  onFatal,
}: {
  uid: string
  onNext: (view: InteractionView) => void
  onFatal: (code: ApiErrorCode) => void
}) {
  const [numeroFiscal, setNumeroFiscal] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!/^\d{13}$/.test(numeroFiscal)) {
      setError(NUMERO_FISCAL_FORMAT)
      return
    }
    if (!password) {
      setError('Saisissez votre mot de passe.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const view = await postLogin(uid, { numero_fiscal: numeroFiscal, password })
      setNumeroFiscal('')
      setPassword('')
      onNext(view) // the server says what comes next: consent, or done
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unexpected'
      if (FATAL.includes(code)) {
        onFatal(code)
        return
      }
      setPassword('')
      setError(API_ERRORS[code])
      setBusy(false)
    }
  }

  return (
    <Layout title="Connexion à votre espace">
      <form method="post" noValidate onSubmit={submit} className="form">
        <div className="field">
          <label htmlFor="numero-fiscal">Numéro fiscal</label>
          <p id="numero-fiscal-aide" className="hint">
            13 chiffres, en haut de votre dernier avis d'impôt.
          </p>
          <input
            id="numero-fiscal"
            inputMode="numeric"
            autoComplete="username"
            maxLength={13}
            aria-describedby="numero-fiscal-aide"
            value={numeroFiscal}
            onChange={(e) => setNumeroFiscal(e.target.value.trim())}
          />
        </div>
        <div className="field">
          <label htmlFor="mot-de-passe">Mot de passe</label>
          <input
            id="mot-de-passe"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="button" disabled={busy}>
          {busy ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
      <ul className="links">
        <li>
          <Link to="/mot-de-passe-oublie">Mot de passe oublié ?</Link>
        </li>
        <li>
          <Link to="/activation">Première connexion ? Activer mon compte</Link>
        </li>
      </ul>
    </Layout>
  )
}
