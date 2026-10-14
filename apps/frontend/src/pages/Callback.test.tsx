import { render, screen } from '@testing-library/react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getSession } from '../auth/session'
import { leaveTo } from '../lib/navigation'
import { beginLogin, callbackSearch } from '../test/oidc'
import Callback from './Callback'

vi.mock('../lib/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/navigation')>()),
  leaveTo: vi.fn(),
}))

function renderAt(url: string) {
  window.history.pushState(null, '', url)
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<p>Accueil du portail</p>} />
        <Route path="/callback" element={<Callback />} />
      </Routes>
    </BrowserRouter>,
  )
}

beforeEach(() => vi.mocked(leaveTo).mockClear())

describe('/callback', () => {
  it('logs in, then lands on the portal with the code gone from the address bar', async () => {
    const authorize = await beginLogin()
    renderAt(`/callback${callbackSearch(authorize)}`)
    expect(await screen.findByText('Accueil du portail')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('')
    expect(getSession()?.user.given_name).toBe('Marie')
  })

  it('refuses a forged state and says so in French', async () => {
    const authorize = await beginLogin()
    renderAt(`/callback${callbackSearch(authorize, { state: 'forged' })}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('ne correspond à aucune demande de cet onglet')
    expect(window.location.search).toBe('') // the code is not left in the history either
    expect(getSession()).toBeNull()
  })

  it('shows our sentence for a refused consent, never the raw parameter', async () => {
    const authorize = await beginLogin()
    renderAt(`/callback?error=access_denied&error_description=%3Cb%3Ehacked%3C%2Fb%3E&state=${authorize.get('state')}`)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("Vous avez refusé l'accès")
    expect(document.body.textContent).not.toContain('hacked')
  })
})
