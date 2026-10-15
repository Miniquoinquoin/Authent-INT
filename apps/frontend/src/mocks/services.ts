/**
 * Fake svc-impots and svc-cadastre (apps/mock-services/src/mockservices/resources.py): same
 * shapes, and the same rule — no Bearer token, 401; token without the route's scope, 403.
 * The scope is read from the mock access token (mocks/oidc.ts), whose signature nobody checks here.
 */
import { http, HttpResponse } from 'msw'
import { decodePayload } from '../auth/claims'
import { CADASTRE_URL, IMPOTS_URL } from '../config'

function guarded(url: string, scope: string, body: object) {
  return http.get(url, ({ request }) => {
    const token = request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1]
    if (!token) return HttpResponse.json({ detail: 'invalid_token' }, { status: 401 })
    let scopes: string[]
    try {
      scopes = (decodePayload<{ scope?: string }>(token).scope ?? '').split(' ')
    } catch {
      return HttpResponse.json({ detail: 'invalid_token' }, { status: 401 })
    }
    if (!scopes.includes(scope)) return HttpResponse.json({ detail: 'insufficient_scope' }, { status: 403 })
    return HttpResponse.json(body)
  })
}

export const serviceHandlers = [
  guarded(`${IMPOTS_URL}/dossiers`, 'svc:impots.read', {
    sub: 'mock',
    dossiers: [
      { id: 'IR-2025-3F2A9C1B', impot: 'revenu', annee: 2025, statut: 'declare' },
      { id: 'TF-2025-7D41E0A2', impot: 'taxe_fonciere', annee: 2025, statut: 'a_payer', montant_eur: 812 },
    ],
  }),
  guarded(`${CADASTRE_URL}/parcelles`, 'svc:cadastre.read', {
    parcelles: [
      { id: 'AB-0012', commune: 'Evry-Courcouronnes', section: 'AB', numero: '0012', contenance_m2: 512, nature: 'sol' },
      { id: 'ZC-0101', commune: 'Lisses', section: 'ZC', numero: '0101', contenance_m2: 24500, nature: 'terre' },
    ],
  }),
]
