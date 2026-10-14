/**
 * Full-page navigations leave the SPA (to the auth-server, or to a client's redirect_uri).
 * One function, so tests can observe them (jsdom can't navigate) and so every exit goes
 * through the same check.
 */

/** Only http(s) — never `javascript:` or `data:` — and no downgrade from an https page. */
export function isSafeRedirect(url: string): boolean {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return false
  }
  if (parsed.protocol === 'https:') return true
  return parsed.protocol === 'http:' && window.location.protocol === 'http:' // local dev / mock only
}

export function leaveTo(url: string): void {
  if (!isSafeRedirect(url)) throw new Error('unsafe redirect')
  window.location.assign(url)
}
