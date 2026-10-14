/**
 * Where the tokens live: a module variable, i.e. this tab's memory. Never localStorage or
 * sessionStorage — any script that runs in the page (an XSS, a compromised dependency) can
 * read Web Storage, and it survives the tab. Cost: a reload forgets them, and "Se connecter"
 * comes back through /authorize, where the __Host-session cookie (SSO) answers without a
 * password. (draft-ietf-oauth-browser-based-apps, "in-memory token storage".)
 */
import { useSyncExternalStore } from 'react'
import type { IdTokenClaims } from './claims'

export interface Session {
  accessToken: string
  idToken: string
  user: IdTokenClaims
  /** Granted scopes: for PRESENTATION only (which tiles to show). Resource Servers enforce. */
  scopes: string[]
  expiresAt: number
}

let current: Session | null = null
const listeners = new Set<() => void>()

export function getSession(): Session | null {
  return current
}

export function setSession(session: Session | null): void {
  current = session
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, getSession)
}
