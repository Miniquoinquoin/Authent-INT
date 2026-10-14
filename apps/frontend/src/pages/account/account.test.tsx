import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { BrowserRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { leaveTo } from '../../lib/navigation'
import { MOCK_LINK_TOKEN, RATE_LIMITED_NUMERO } from '../../mocks/data'
import { server } from '../../mocks/node'
import { ChoosePassword } from './ChoosePassword'
import { RequestLink } from './RequestLink'

vi.mock('../../lib/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/navigation')>()),
  leaveTo: vi.fn(),
}))

const AUTH = 'https://auth.authentint.test'
const GOOD_PASSWORD = 'une phrase de passe assez longue'

function renderAt(url: string) {
  window.history.pushState(null, '', url)
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="/activation" element={<RequestLink kind="activation" />} />
        <Route path="/mot-de-passe-oublie" element={<RequestLink kind="reset" />} />
        <Route path="/activate" element={<ChoosePassword kind="activation" />} />
        <Route path="/reset-password" element={<ChoosePassword kind="reset" />} />
      </Routes>
    </BrowserRouter>,
  )
}

async function askLink(numero: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Numéro fiscal'), numero)
  await user.click(screen.getByRole('button', { name: 'Recevoir le lien' }))
}

async function choose(password: string, confirmation = password) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Mot de passe'), password)
  await user.type(screen.getByLabelText('Confirmez le mot de passe'), confirmation)
  await user.click(screen.getByRole('button', { name: 'Enregistrer le mot de passe' }))
  return user
}

beforeEach(() => vi.mocked(leaveTo).mockClear())
afterEach(() => server.events.removeAllListeners())

describe.each([
  ['activation', '/activation', '/account/activation/request'],
  ['reset', '/mot-de-passe-oublie', '/account/password-reset/request'],
])('asking for a %s link', (_, route, endpoint) => {
  it('shows one neutral sentence, the same for a known and an unknown account', async () => {
    const answers: string[] = []
    for (const numero of ['1234567890123', '9999999999999']) {
      const { unmount } = renderAt(route)
      await askLink(numero)
      answers.push((await screen.findByRole('status')).textContent!)
      unmount()
    }
    expect(answers[0]).toMatch(/^Si ce numéro fiscal correspond à un compte/)
    expect(answers[1]).toBe(answers[0])
  })

  it('posts the number in the body, never in the URL', async () => {
    let seen: { url: string; body: unknown } | undefined
    server.events.on('request:start', async ({ request }) => {
      seen = { url: request.url, body: await request.clone().json() }
    })
    renderAt(route)
    await askLink('1234567890123')
    await screen.findByRole('status')
    expect(seen).toEqual({ url: `${AUTH}${endpoint}`, body: { numero_fiscal: '1234567890123' } })
    expect(window.location.href).not.toContain('1234567890123')
  })

  it('checks the 13 digits first', async () => {
    renderAt(route)
    await askLink('123')
    expect(await screen.findByRole('alert')).toHaveTextContent('13 chiffres')
  })

  it('says to slow down on 429', async () => {
    renderAt(route)
    await askLink(RATE_LIMITED_NUMERO)
    expect(await screen.findByRole('alert')).toHaveTextContent('Trop de tentatives')
  })
})

describe.each([
  ['activation', '/activate', 'Votre compte est activé.', '/account/activation/confirm'],
  ['reset', '/reset-password', 'Votre mot de passe a été modifié.', '/account/password-reset/confirm'],
])('choosing a password (%s)', (_, route, success, endpoint) => {
  it('removes the token from the address bar as soon as it is read', async () => {
    renderAt(`${route}?token=${MOCK_LINK_TOKEN}`)
    await screen.findByLabelText('Mot de passe')
    expect(window.location.pathname).toBe(route)
    expect(window.location.search).toBe('')
    expect(window.location.href).not.toContain(MOCK_LINK_TOKEN)
  })

  it('sends the token read from the link with the new password', async () => {
    let body: unknown
    server.events.on('request:start', async ({ request }) => {
      if (request.url === `${AUTH}${endpoint}`) body = await request.clone().json()
    })
    renderAt(`${route}?token=${MOCK_LINK_TOKEN}`)
    const user = await choose(GOOD_PASSWORD)
    expect(await screen.findByRole('status')).toHaveTextContent(success)
    expect(body).toEqual({ token: MOCK_LINK_TOKEN, password: GOOD_PASSWORD })

    await user.click(screen.getByRole('button', { name: 'Se connecter' }))
    await vi.waitFor(() => expect(leaveTo).toHaveBeenCalledWith(expect.stringContaining(`${AUTH}/authorize?`)))
  })

  it('refuses two different passwords without calling the server', async () => {
    let called = false
    server.events.on('request:start', () => {
      called = true
    })
    renderAt(`${route}?token=${MOCK_LINK_TOKEN}`)
    await choose(GOOD_PASSWORD, `${GOOD_PASSWORD}!`)
    expect(await screen.findByRole('alert')).toHaveTextContent('Les deux mots de passe ne sont pas identiques.')
    expect(called).toBe(false)
  })

  it('asks for 12 characters at least', async () => {
    renderAt(`${route}?token=${MOCK_LINK_TOKEN}`)
    await choose('trop-court')
    expect(await screen.findByRole('alert')).toHaveTextContent('au moins 12 caractères')
  })

  it('an expired or used link → our sentence and a way to ask a new one', async () => {
    renderAt(`${route}?token=lien-deja-utilise`)
    await choose(GOOD_PASSWORD)
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien est invalide, a expiré ou a déjà été utilisé.')
    expect(screen.getByRole('link', { name: /Demander un nouveau lien/ })).toBeInTheDocument()
  })

  it('no token at all → same sentence, no form', async () => {
    renderAt(route)
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien est invalide')
    expect(screen.queryByLabelText('Mot de passe')).not.toBeInTheDocument()
  })

  it('maps a server-side 422 to our sentence', async () => {
    server.use(http.post(`${AUTH}${endpoint}`, () => HttpResponse.json({ detail: [] }, { status: 422 })))
    renderAt(`${route}?token=${MOCK_LINK_TOKEN}`)
    await choose(GOOD_PASSWORD)
    expect(await screen.findByRole('alert')).toHaveTextContent('Les informations saisies ne sont pas valides.')
  })
})
