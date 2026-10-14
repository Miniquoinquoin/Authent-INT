import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getSession, setSession } from '../auth/session'
import type { IdTokenClaims } from '../auth/claims'
import { leaveTo } from '../lib/navigation'
import Portal from './Portal'

vi.mock('../lib/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/navigation')>()),
  leaveTo: vi.fn(),
}))

const AUTH = 'https://auth.authentint.test'

function logInWith(scopes: string[], role: IdTokenClaims['role'] = 'agent') {
  setSession({
    accessToken: 'access',
    idToken: 'id',
    scopes,
    expiresAt: Date.now() + 600_000,
    user: {
      iss: AUTH, sub: 's', aud: 'portail-web', exp: 0, iat: 0, auth_time: 0, nonce: 'n', acr: 'urn:authentint:acr:pwd',
      amr: ['pwd'], sid: 'sid', name: 'Marie Dupont', given_name: 'Marie', family_name: 'Dupont', role,
    },
  })
}

function renderPortal() {
  render(
    <MemoryRouter>
      <Portal />
    </MemoryRouter>,
  )
}

beforeEach(() => vi.mocked(leaveTo).mockClear())

describe('portal', () => {
  it('logged out: "Se connecter" starts the OIDC flow', async () => {
    renderPortal()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Se connecter' }))
    await vi.waitFor(() => expect(leaveTo).toHaveBeenCalledWith(expect.stringMatching(new RegExp(`^${AUTH}/authorize\\?`))))
  })

  it('greets the user with the name from the ID token', () => {
    logInWith(['openid'])
    renderPortal()
    expect(screen.getByRole('heading', { name: 'Bonjour, Marie Dupont' })).toBeInTheDocument()
  })

  it.each([
    ['agent', ['openid', 'svc:impots.read', 'svc:impots.write', 'svc:cadastre.read'], ['impots', 'cadastre']],
    ['contribuable', ['openid', 'svc:impots.read'], ['impots']],
    ['nothing granted', ['openid'], []],
  ])('shows the tiles the granted scopes allow (%s)', (_, scopes, tiles) => {
    logInWith(scopes)
    renderPortal()
    for (const id of ['impots', 'cadastre']) {
      if (tiles.includes(id)) expect(screen.getByTestId(`tuile-${id}`)).toBeInTheDocument()
      else expect(screen.queryByTestId(`tuile-${id}`)).not.toBeInTheDocument()
    }
    if (tiles.length === 0) expect(screen.getByText(/Aucun service/)).toBeInTheDocument()
  })

  it('tells read-only from read-write', () => {
    logInWith(['openid', 'svc:impots.read', 'svc:impots.write', 'svc:cadastre.read'])
    renderPortal()
    expect(screen.getByTestId('tuile-impots')).toHaveTextContent('Consultation et modification')
    expect(screen.getByTestId('tuile-cadastre')).toHaveTextContent(/Consultation$/)
  })

  it('"Se déconnecter" forgets the tokens and goes to end-session', async () => {
    logInWith(['openid'])
    renderPortal()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Se déconnecter' }))
    expect(getSession()).toBeNull()
    expect(leaveTo).toHaveBeenCalledWith(expect.stringMatching(new RegExp(`^${AUTH}/end-session\\?`)))
  })
})
