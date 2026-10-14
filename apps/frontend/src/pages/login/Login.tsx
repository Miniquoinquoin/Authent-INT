/**
 * /login?uid=… — the step machine (architecture.md §4, ADR §10 step 8).
 *
 * This screen decides NOTHING about the order of the steps. It asks the server what the
 * pending authentication needs (`GET /interaction/{uid}` → `prompt`), shows that screen,
 * and after each POST shows whatever `prompt` the server answered. `prompt: null` means
 * finished: follow `redirect_to`. Adding the second factor (MFA) is a new `prompt` value
 * and a new step component here, nothing else.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ApiError, type ApiErrorCode } from '../../api/client'
import { getInteraction, type InteractionView } from '../../api/interaction'
import { Alert, Layout } from '../../components/Layout'
import { isSafeRedirect, leaveTo } from '../../lib/navigation'
import { API_ERRORS } from '../../messages'
import { ConsentStep } from './ConsentStep'
import { LoginStep } from './LoginStep'

type Screen =
  | { kind: 'loading' }
  | { kind: 'step'; view: InteractionView }
  | { kind: 'leaving' }
  | { kind: 'failed'; code: ApiErrorCode }

export default function Login() {
  const [params] = useSearchParams()
  const uid = params.get('uid')
  const [screen, setScreen] = useState<Screen>(uid ? { kind: 'loading' } : { kind: 'failed', code: 'unknown_interaction' })

  /** Whatever the server answered is the next screen. */
  const show = useCallback((view: InteractionView) => {
    if (view.prompt !== null) {
      setScreen({ kind: 'step', view })
      return
    }
    if (!view.redirect_to || !isSafeRedirect(view.redirect_to)) {
      setScreen({ kind: 'failed', code: 'unexpected' })
      return
    }
    setScreen({ kind: 'leaving' })
    leaveTo(view.redirect_to) // back to /authorize, which issues the code (or the client's error URL)
  }, [])

  const fail = useCallback((code: ApiErrorCode) => setScreen({ kind: 'failed', code }), [])

  useEffect(() => {
    if (!uid) return
    let live = true
    getInteraction(uid).then(
      (view) => live && show(view),
      (e: unknown) => live && fail(e instanceof ApiError ? e.code : 'unexpected'),
    )
    return () => {
      live = false
    }
  }, [uid, show, fail])

  switch (screen.kind) {
    case 'loading':
      return (
        <Layout title="Connexion">
          <p role="status">Chargement…</p>
        </Layout>
      )
    case 'leaving':
      return (
        <Layout title="Connexion">
          <p role="status">Redirection en cours…</p>
        </Layout>
      )
    case 'failed':
      return (
        <Layout title="Connexion impossible">
          <Alert>{API_ERRORS[screen.code]}</Alert>
          <p>
            <Link to="/">Recommencer depuis le portail</Link>
          </p>
        </Layout>
      )
    case 'step':
      switch (screen.view.prompt) {
        case 'login':
          return <LoginStep uid={uid!} onNext={show} onFatal={fail} />
        case 'consent':
          return <ConsentStep uid={uid!} view={screen.view} onNext={show} onFatal={fail} />
        default:
          // A prompt this build doesn't know (the server is newer): don't guess, start over
          return (
            <Layout title="Connexion impossible">
              <Alert>{API_ERRORS.unexpected}</Alert>
            </Layout>
          )
      }
  }
}
