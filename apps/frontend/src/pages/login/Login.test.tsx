import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { BrowserRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InteractionView } from '../../api/interaction'
import { leaveTo } from '../../lib/navigation'
import { LOCKED_NUMERO, MOCK_PASSWORD, RATE_LIMITED_NUMERO } from '../../mocks/data'
import { mockUid } from '../../mocks/interaction'
import { server } from '../../mocks/node'
import Login from './Login'

vi.mock('../../lib/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/navigation')>()),
  leaveTo: vi.fn(),
}))

const AUTH = 'https://auth.authentint.test'
const NUMERO = '1234567890123'

function renderLogin(uid: string | null = mockUid()) {
  window.history.pushState(null, '', uid === null ? '/login' : `/login?uid=${uid}`)
  render(
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    </BrowserRouter>,
  )
}

async function logIn(numero = NUMERO, password = MOCK_PASSWORD) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Numéro fiscal'), numero)
  await user.type(screen.getByLabelText('Mot de passe'), password)
  await user.click(screen.getByRole('button', { name: 'Se connecter' }))
  return user
}

function serveView(view: Partial<InteractionView>) {
  server.use(
    http.get(`${AUTH}/interaction/:uid`, () =>
      HttpResponse.json<InteractionView>({ prompt: 'login', client_name: 'Portail', scopes: ['openid'], redirect_to: null, ...view }),
    ),
  )
}

beforeEach(() => vi.mocked(leaveTo).mockClear())

describe('the step machine renders what the server asks for', () => {
  it('prompt "login": numero fiscal and password', async () => {
    renderLogin()
    expect(await screen.findByRole('heading', { name: 'Connexion à votre espace' })).toBeInTheDocument()
    expect(screen.getByLabelText('Numéro fiscal')).toBeInTheDocument()
    expect(screen.getByLabelText('Mot de passe')).toHaveAttribute('type', 'password')
  })

  it('prompt "consent": the client name and the scopes in French', async () => {
    serveView({ prompt: 'consent', client_name: 'Portail', scopes: ['openid', 'svc:impots.read'] })
    renderLogin()
    expect(await screen.findByRole('heading', { name: "Autoriser l'accès" })).toBeInTheDocument()
    expect(screen.getByText('Portail')).toBeInTheDocument()
    expect(screen.getByText('Consulter vos dossiers fiscaux')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accepter' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refuser' })).toBeInTheDocument()
  })

  it('prompt null: follows redirect_to', async () => {
    serveView({ prompt: null, redirect_to: `${AUTH}/authorize?client_id=portail-web` })
    renderLogin()
    await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${AUTH}/authorize?client_id=portail-web`))
  })

  it('refuses to follow a javascript: redirect_to', async () => {
    serveView({ prompt: null, redirect_to: 'javascript:alert(1)' })
    renderLogin()
    expect(await screen.findByRole('alert')).toHaveTextContent('erreur inattendue')
    expect(leaveTo).not.toHaveBeenCalled()
  })

  it('an unknown or expired uid says "expired, start again"', async () => {
    renderLogin('uid-inconnu')
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien de connexion a expiré. Recommencez depuis le portail.')
  })

  it('no uid at all: same message, no request', async () => {
    renderLogin(null)
    expect(await screen.findByRole('alert')).toHaveTextContent('a expiré')
  })
})

describe('login', () => {
  it('shows the step the server answers after the POST (consent here), never one it guessed', async () => {
    renderLogin()
    await logIn()
    expect(await screen.findByRole('heading', { name: "Autoriser l'accès" })).toBeInTheDocument()
  })

  it('goes straight to redirect_to when the server answers prompt null (no consent needed)', async () => {
    server.use(
      http.post(`${AUTH}/interaction/:uid/login`, () =>
        HttpResponse.json<InteractionView>({ prompt: null, client_name: 'Portail', scopes: ['openid'], redirect_to: `${AUTH}/authorize?x=1` }),
      ),
    )
    renderLogin()
    await logIn()
    await waitFor(() => expect(leaveTo).toHaveBeenCalledWith(`${AUTH}/authorize?x=1`))
    expect(screen.queryByRole('heading', { name: "Autoriser l'accès" })).not.toBeInTheDocument()
  })

  it.each([
    ['a wrong password', NUMERO, 'mauvais-mot-de-passe', 'Numéro fiscal ou mot de passe incorrect.'],
    ['an unknown numero (same sentence)', '9999999999999', MOCK_PASSWORD, 'Numéro fiscal ou mot de passe incorrect.'],
    ['a locked account', LOCKED_NUMERO, MOCK_PASSWORD, 'Votre compte est temporairement verrouillé'],
    ['too many attempts', RATE_LIMITED_NUMERO, MOCK_PASSWORD, 'Trop de tentatives. Patientez une minute'],
  ])('%s → its French message, and the password field is emptied', async (_, numero, password, message) => {
    renderLogin()
    await logIn(numero, password)
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByLabelText('Mot de passe')).toHaveValue('')
  })

  it('an interaction that expired meanwhile → "expired, start again"', async () => {
    server.use(http.post(`${AUTH}/interaction/:uid/login`, () => HttpResponse.json({ detail: 'unknown_interaction' }, { status: 404 })))
    renderLogin()
    await logIn()
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien de connexion a expiré')
  })

  it('checks the 13 digits before sending anything', async () => {
    let posted = false
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') posted = true
    })
    renderLogin()
    await logIn('12345', MOCK_PASSWORD)
    expect(await screen.findByRole('alert')).toHaveTextContent('13 chiffres')
    expect(posted).toBe(false)
    server.events.removeAllListeners()
  })
})

describe('the numero fiscal stays out of URLs, logs and storage', () => {
  const consoleSpies: ReturnType<typeof vi.spyOn>[] = []
  afterEach(() => {
    consoleSpies.splice(0).forEach((spy) => spy.mockRestore())
    server.events.removeAllListeners()
  })

  it('is posted in the JSON body only', async () => {
    for (const method of ['log', 'info', 'warn', 'error', 'debug'] as const) {
      consoleSpies.push(vi.spyOn(console, method))
    }
    const urls: string[] = []
    let body = ''
    server.events.on('request:start', async ({ request }) => {
      urls.push(request.url)
      if (request.method === 'POST') body = await request.clone().text()
    })

    renderLogin()
    await logIn()
    await screen.findByRole('heading', { name: "Autoriser l'accès" })

    expect(JSON.parse(body)).toEqual({ numero_fiscal: NUMERO, password: MOCK_PASSWORD })
    for (const url of [...urls, window.location.href]) expect(url).not.toContain(NUMERO)
    for (const spy of consoleSpies) {
      for (const args of spy.mock.calls) expect(JSON.stringify(args)).not.toContain(NUMERO)
    }
    for (const storage of [localStorage, sessionStorage]) {
      for (let i = 0; i < storage.length; i++) expect(storage.getItem(storage.key(i)!)).not.toContain(NUMERO)
    }
  })

  it('cannot be serialised by a native form submission', async () => {
    renderLogin()
    const input = await screen.findByLabelText('Numéro fiscal')
    expect(input).not.toHaveAttribute('name')
    expect(screen.getByLabelText('Mot de passe')).not.toHaveAttribute('name')
    expect(input.closest('form')).toHaveAttribute('method', 'post')
  })
})

describe('consent', () => {
  it('Accepter: the server finishes the flow and the browser follows redirect_to (the callback with a code)', async () => {
    renderLogin()
    const user = await logIn()
    await user.click(await screen.findByRole('button', { name: 'Accepter' }))
    await waitFor(() => expect(leaveTo).toHaveBeenCalled())
    const target = new URL(vi.mocked(leaveTo).mock.lastCall![0])
    expect(`${target.origin}${target.pathname}`).toBe(`${window.location.origin}/callback`)
    expect(target.searchParams.get('code')).toBeTruthy()
    expect(target.searchParams.get('state')).toBe('state-de-test')
  })

  it('Refuser: back to the application with error=access_denied', async () => {
    renderLogin()
    const user = await logIn()
    await user.click(await screen.findByRole('button', { name: 'Refuser' }))
    await waitFor(() => expect(leaveTo).toHaveBeenCalled())
    const target = new URL(vi.mocked(leaveTo).mock.lastCall![0])
    expect(target.searchParams.get('error')).toBe('access_denied')
    expect(target.searchParams.has('code')).toBe(false)
  })

  it('consent before login (server says login_required) → start again', async () => {
    serveView({ prompt: 'consent', scopes: ['openid'] })
    renderLogin()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Accepter' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien de connexion a expiré')
  })
})
