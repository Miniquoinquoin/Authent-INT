/**
 * Fake of the account lifecycle (flows/activation.py, flows/reset.py).
 * `request`: 202 `{"status":"accepted"}` for ANY well-formed number — the real server answers
 * the same whether the account exists or not, and so does the mock. `confirm`: only
 * MOCK_LINK_TOKEN is a valid link; anything else is `invalid_token`, like an expired one.
 */
import { http, HttpResponse } from 'msw'
import type { Schemas } from '../api/client'
import { AUTH_URL } from '../config'
import { MOCK_LINK_TOKEN, RATE_LIMITED_NUMERO } from './data'

const validationError = () => HttpResponse.json({ detail: [{ loc: ['body'], msg: 'invalid', type: 'value_error' }] }, { status: 422 })

function request(path: string) {
  return http.post<never, Schemas['ActivationRequest']>(`${AUTH_URL}${path}`, async ({ request }) => {
    const body = await request.json()
    if (!/^\d{13}$/.test(body?.numero_fiscal ?? '')) return validationError()
    if (body.numero_fiscal === RATE_LIMITED_NUMERO) return HttpResponse.json({ detail: 'too_many_attempts' }, { status: 429 })
    return HttpResponse.json({ status: 'accepted' }, { status: 202 })
  })
}

function confirm(path: string, done: string) {
  return http.post<never, Schemas['ActivationConfirm']>(`${AUTH_URL}${path}`, async ({ request }) => {
    const body = await request.json()
    const password = body?.password ?? ''
    if (!body?.token || password.length < 12 || password.length > 256) return validationError()
    if (body.token !== MOCK_LINK_TOKEN) return HttpResponse.json({ detail: 'invalid_token' }, { status: 400 })
    return HttpResponse.json({ status: done })
  })
}

export const accountHandlers = [
  request('/account/activation/request'),
  confirm('/account/activation/confirm', 'activated'),
  request('/account/password-reset/request'),
  confirm('/account/password-reset/confirm', 'password_changed'),
]
