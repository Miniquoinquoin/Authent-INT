import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ApiError, type ApiErrorCode } from '../api/client'
import { getResource } from '../api/resources'
import { startLogin } from '../auth/oidc'
import { useSession } from '../auth/session'
import { Alert, Layout } from '../components/Layout'
import { API_ERRORS } from '../messages'
import type { Service } from '../services'

type Row = Record<string, string | number | null | undefined>

/**
 * /impots, /cadastre — what the service itself answers to this user's access token.
 * The page only asks: the Resource Server decides (401/403), never this screen.
 */
export default function ServicePage({ service }: { service: Service }) {
  const session = useSession()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState<ApiErrorCode | null>(null)

  useEffect(() => {
    if (!session) return
    let live = true // a late answer must not land on a page we already left
    getResource<Record<string, Row[]>>(service.endpoint, session.accessToken)
      .then((body) => live && setRows(body[service.listKey] ?? []))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.code : 'unexpected'))
    return () => {
      live = false
    }
  }, [session, service])

  const back = (
    <p className="links">
      <Link to="/">Retour au portail</Link>
    </p>
  )

  if (!session) {
    return (
      <Layout title={service.title}>
        <p>Connectez-vous depuis le portail pour accéder à ce service.</p>
        {back}
      </Layout>
    )
  }

  return (
    <Layout title={service.title} wide>
      <p className="subtitle">{service.description}</p>
      {error ? (
        <>
          <Alert>{API_ERRORS[error]}</Alert>
          {error === 'session_expired' && (
            <div className="actions">
              <button type="button" className="button" onClick={() => void startLogin()}>
                Se reconnecter
              </button>
            </div>
          )}
        </>
      ) : rows === null ? (
        <p role="status">Chargement…</p>
      ) : rows.length === 0 ? (
        <p>Aucun élément pour le moment.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {service.columns.map((c) => (
                  <th key={c.key} scope="col">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={String(row.id ?? i)}>
                  {service.columns.map((c) => (
                    <td key={c.key}>{row[c.key] ?? '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {back}
    </Layout>
  )
}
