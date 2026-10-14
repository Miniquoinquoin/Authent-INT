/**
 * Interaction API (ADR §9): one pending /authorize, driven step by step.
 * Every call answers an `InteractionView`: the SERVER says which step comes next.
 */
import { apiUrl, call, type Schemas } from './client'

export type InteractionView = Schemas['InteractionView']
export type Prompt = InteractionView['prompt']
export type LoginBody = Schemas['LoginBody']
export type ConsentBody = Schemas['ConsentBody']

export function getInteraction(uid: string): Promise<InteractionView> {
  return call('GET', apiUrl('/interaction/{uid}', { uid }))
}

export function postLogin(uid: string, body: LoginBody): Promise<InteractionView> {
  return call('POST', apiUrl('/interaction/{uid}/login', { uid }), body)
}

export function postConsent(uid: string, body: ConsentBody): Promise<InteractionView> {
  return call('POST', apiUrl('/interaction/{uid}/consent', { uid }), body)
}
