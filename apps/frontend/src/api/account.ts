/**
 * Account lifecycle (ADR §9 "Cycle de vie du compte").
 *
 * The two `request` endpoints answer 202 `{"status":"accepted"}` whether the account exists
 * or not (invariant 8): the screens show one neutral sentence, whatever happened.
 * The OpenAPI declares no response body for these routes, hence the local types.
 */
import { apiUrl, call, type Schemas } from './client'

export type Accepted = { status: 'accepted' }

export function requestActivation(body: Schemas['ActivationRequest']): Promise<Accepted> {
  return call('POST', apiUrl('/account/activation/request'), body)
}

export function confirmActivation(body: Schemas['ActivationConfirm']): Promise<{ status: 'activated' }> {
  return call('POST', apiUrl('/account/activation/confirm'), body)
}

export function requestPasswordReset(body: Schemas['ResetRequest']): Promise<Accepted> {
  return call('POST', apiUrl('/account/password-reset/request'), body)
}

export function confirmPasswordReset(body: Schemas['ResetConfirm']): Promise<{ status: 'password_changed' }> {
  return call('POST', apiUrl('/account/password-reset/confirm'), body)
}
