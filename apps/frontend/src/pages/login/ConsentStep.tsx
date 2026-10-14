import { useState } from 'react'
import { ApiError, type ApiErrorCode } from '../../api/client'
import { postConsent, type InteractionView } from '../../api/interaction'
import { Alert, Layout } from '../../components/Layout'
import { API_ERRORS } from '../../messages'
import { describeScope, isKnownScope } from '../../scopes'

/**
 * prompt = "consent": which application asks for what, in plain French.
 * Refusing is a normal answer: the server ends the flow and sends the browser back to the
 * application with `error=access_denied`.
 */
export function ConsentStep({
  uid,
  view,
  onNext,
  onFatal,
}: {
  uid: string
  view: InteractionView
  onNext: (view: InteractionView) => void
  onFatal: (code: ApiErrorCode) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function answer(approve: boolean) {
    setBusy(true)
    setError(null)
    try {
      onNext(await postConsent(uid, { approve }))
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unexpected'
      if (code === 'network' || code === 'too_many_attempts') {
        setError(API_ERRORS[code])
        setBusy(false)
        return
      }
      onFatal(code) // unknown_interaction, login_required...: this uid can't go further
    }
  }

  return (
    <Layout title="Autoriser l'accès">
      <p>
        L'application <strong>{view.client_name}</strong> souhaite :
      </p>
      <ul className="scopes">
        {view.scopes.map((scope) => (
          <li key={scope}>
            {describeScope(scope)}
            {!isKnownScope(scope) && <code>{scope}</code>}
          </li>
        ))}
      </ul>
      {error && <Alert>{error}</Alert>}
      <div className="actions">
        <button type="button" className="button" disabled={busy} onClick={() => void answer(true)}>
          Accepter
        </button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void answer(false)}>
          Refuser
        </button>
      </div>
    </Layout>
  )
}
