import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { requestActivation, requestPasswordReset } from '../../api/account'
import { ApiError } from '../../api/client'
import { Alert, Layout, Notice } from '../../components/Layout'
import { API_ERRORS, NUMERO_FISCAL_FORMAT } from '../../messages'

const TEXT = {
  activation: {
    title: 'Activer mon compte',
    intro: 'Saisissez votre numéro fiscal : vous recevrez par e-mail un lien pour choisir votre mot de passe.',
    // One sentence whatever happened (invariant 8): it must not reveal whether the account exists
    done:
      "Si ce numéro fiscal correspond à un compte en attente d'activation, un lien vient d'être envoyé à l'adresse e-mail associée. Il est valable 30 minutes.",
    send: requestActivation,
  },
  reset: {
    title: 'Mot de passe oublié',
    intro: 'Saisissez votre numéro fiscal : vous recevrez par e-mail un lien pour choisir un nouveau mot de passe.',
    done:
      "Si ce numéro fiscal correspond à un compte actif, un lien de réinitialisation vient d'être envoyé à l'adresse e-mail associée. Il est valable 30 minutes.",
    send: requestPasswordReset,
  },
}

/** /activation and /mot-de-passe-oublie: ask for a link by e-mail. */
export function RequestLink({ kind }: { kind: 'activation' | 'reset' }) {
  const text = TEXT[kind]
  const [numeroFiscal, setNumeroFiscal] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!/^\d{13}$/.test(numeroFiscal)) {
      setError(NUMERO_FISCAL_FORMAT)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await text.send({ numero_fiscal: numeroFiscal })
      setNumeroFiscal('') // nothing to keep once it is sent
      setDone(true)
    } catch (e) {
      setError(API_ERRORS[e instanceof ApiError ? e.code : 'unexpected'])
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <Layout title={text.title}>
        <Notice>{text.done}</Notice>
        <p>Pensez à vérifier vos courriers indésirables.</p>
        <p>
          <Link to="/">Retour à l'accueil</Link>
        </p>
      </Layout>
    )
  }

  return (
    <Layout title={text.title}>
      <p>{text.intro}</p>
      {/* method="post" and no `name`: a native submission could never put the number in a URL */}
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
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="button" disabled={busy}>
          {busy ? 'Envoi…' : 'Recevoir le lien'}
        </button>
      </form>
      <p>
        <Link to="/">Retour à l'accueil</Link>
      </p>
    </Layout>
  )
}
