import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../mocks/node'
import { ApiError, apiUrl, call } from './client'

const AUTH = 'https://auth.authentint.test'

async function errorOf(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (e) {
    if (e instanceof ApiError) return e
    throw e
  }
  throw new Error('expected an ApiError')
}

describe('apiUrl', () => {
  it('fills and encodes path parameters from the contract', () => {
    expect(apiUrl('/interaction/{uid}/login', { uid: 'a/b?c' })).toBe(`${AUTH}/interaction/a%2Fb%3Fc/login`)
  })
})

describe('call', () => {
  it('sends JSON with credentials so the session cookie is kept', async () => {
    let seen: { credentials: RequestCredentials; type: string | null; body: unknown } | undefined
    server.use(
      http.post(`${AUTH}/account/activation/request`, async ({ request }) => {
        seen = { credentials: request.credentials, type: request.headers.get('content-type'), body: await request.json() }
        return HttpResponse.json({ status: 'accepted' }, { status: 202 })
      }),
    )
    await expect(call('POST', `${AUTH}/account/activation/request`, { numero_fiscal: '1234567890123' })).resolves.toEqual({
      status: 'accepted',
    })
    expect(seen).toEqual({ credentials: 'include', type: 'application/json', body: { numero_fiscal: '1234567890123' } })
  })

  it.each([
    [401, 'invalid_credentials'],
    [423, 'account_locked'],
    [429, 'too_many_attempts'],
    [404, 'unknown_interaction'],
    [400, 'login_required'],
    [400, 'invalid_token'],
  ])('maps %i {"detail":"%s"} to that code', async (status, detail) => {
    server.use(http.get(`${AUTH}/x`, () => HttpResponse.json({ detail }, { status })))
    const error = await errorOf(call('GET', `${AUTH}/x`))
    expect(error.code).toBe(detail)
    expect(error.status).toBe(status)
  })

  it('maps 422 to validation, whatever the detail list says', async () => {
    server.use(http.get(`${AUTH}/x`, () => HttpResponse.json({ detail: [{ msg: 'bad' }] }, { status: 422 })))
    expect((await errorOf(call('GET', `${AUTH}/x`))).code).toBe('validation')
  })

  it('never surfaces a server-chosen sentence', async () => {
    server.use(http.get(`${AUTH}/x`, () => HttpResponse.json({ detail: '<b>pwned</b>' }, { status: 500 })))
    const error = await errorOf(call('GET', `${AUTH}/x`))
    expect(error.code).toBe('unexpected')
    expect(error.message).toBe('unexpected')
  })

  it('falls back on the status when the body is not JSON', async () => {
    server.use(http.get(`${AUTH}/x`, () => new HttpResponse('<html>busy</html>', { status: 429 })))
    expect((await errorOf(call('GET', `${AUTH}/x`))).code).toBe('too_many_attempts')
  })

  it('reports a network failure as such', async () => {
    server.use(http.get(`${AUTH}/x`, () => HttpResponse.error()))
    expect((await errorOf(call('GET', `${AUTH}/x`))).code).toBe('network')
  })
})
