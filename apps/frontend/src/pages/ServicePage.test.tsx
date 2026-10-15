import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { setSession } from '../auth/session'
import type { IdTokenClaims } from '../auth/claims'
import { mockJwt } from '../mocks/encoding'
import { server } from '../mocks/node'
import { SERVICES } from '../services'
import ServicePage from './ServicePage'

const [IMPOTS, CADASTRE] = SERVICES

function logInWith(scope: string) {
  setSession({
    accessToken: mockJwt({ scope }, 'at+jwt'),
    idToken: 'id',
    scopes: scope.split(' '),
    expiresAt: Date.now() + 600_000,
    user: { sub: 's', name: 'Marie Dupont', role: 'contribuable' } as IdTokenClaims,
  })
}

function renderPage(service = IMPOTS) {
  render(
    <MemoryRouter>
      <ServicePage service={service} />
    </MemoryRouter>,
  )
}

describe('service page', () => {
  it('logged out: no call, a way back to the portal', () => {
    renderPage()
    expect(screen.getByRole('link', { name: 'Retour au portail' })).toHaveAttribute('href', '/')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lists what the service answers, asking with the access token', async () => {
    logInWith('openid svc:impots.read')
    let authorization: string | null = null
    server.events.on('request:start', ({ request }) => {
      if (request.url === IMPOTS.endpoint) authorization = request.headers.get('Authorization')
    })
    renderPage()
    expect(await screen.findByText('TF-2025-7D41E0A2')).toBeInTheDocument()
    expect(screen.getByText('812')).toBeInTheDocument()
    expect(authorization).toMatch(/^Bearer /)
    server.events.removeAllListeners()
  })

  it('cadastre: its own columns', async () => {
    logInWith('openid svc:cadastre.read')
    renderPage(CADASTRE)
    expect(await screen.findByText('Evry-Courcouronnes')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Surface (m²)' })).toBeInTheDocument()
  })

  it('403: says the account has no access', async () => {
    logInWith('openid svc:cadastre.read') // no svc:impots.read: the (mock) service refuses
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent("n'a pas accès")
  })

  it('401: offers to log in again', async () => {
    logInWith('openid svc:impots.read')
    server.use(http.get(IMPOTS.endpoint, () => HttpResponse.json({ detail: 'invalid_token' }, { status: 401 })))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('session a expiré')
    expect(screen.getByRole('button', { name: 'Se reconnecter' })).toBeInTheDocument()
  })
})
