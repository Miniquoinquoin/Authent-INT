/**
 * Calls to the Resource Servers (svc-impots, svc-cadastre). Unlike api/client.ts, no cookie:
 * the access token goes in `Authorization: Bearer`, and the service checks it on its own (ADR §11).
 */
import { ApiError } from './client'

export async function getResource<T>(url: string, accessToken: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` } })
  } catch {
    throw new ApiError('network', 0)
  }
  if (response.status === 401) throw new ApiError('session_expired', 401) // expired (10 min) or revoked
  if (response.status === 403) throw new ApiError('forbidden', 403) // insufficient_scope
  if (!response.ok) throw new ApiError('unexpected', response.status)
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError('unexpected', response.status)
  }
}
