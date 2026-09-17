/**
 * One fetch wrapper: relative `/api`, credentials included, errors normalised.
 *
 * Stores nothing. There is no identity in `localStorage` and no client-side
 * route guard worth the name — the cookie is the state, and a 401 is the
 * server telling us what we are not allowed to know any other way (P§3).
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    /** The server's own words. The UI renders this verbatim and never rewrites it. */
    readonly detail: string,
  ) {
    super(detail);
  }
}

/** The stage the server says this authentication is at. It decides, not us. */
export type Stage = "login" | "mfa" | "done";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Service injoignable. Vérifiez votre connexion.");
  }

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // The server's failure constant is the message. Composing our own here is
    // exactly how the enumeration property of P§7 step 4 would die.
    throw new ApiError(response.status, body?.detail ?? "Une erreur est survenue.");
  }
  return body as T;
}

export const api = {
  startInteraction: () => request<{ uid: string }>("/interaction", { method: "POST" }),

  stage: (uid: string) => request<{ stage: Stage }>(`/interaction/${uid}`),

  login: (uid: string, numero_fiscal: string, password: string) =>
    request<{ stage: Stage }>(`/interaction/${uid}/login`, {
      method: "POST",
      body: JSON.stringify({ numero_fiscal, password }),
    }),

  sendOtp: (uid: string) =>
    request<{ stage: Stage }>(`/interaction/${uid}/mfa/send`, { method: "POST" }),

  verifyOtp: (uid: string, code: string) =>
    request<{ stage: Stage }>(`/interaction/${uid}/mfa/verify`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  activate: (token: string, password: string) =>
    request<void>("/account/activation/confirm", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  me: () =>
    request<{
      nom: string;
      prenom: string;
      role: string;
      statut: string;
      session_ouverte_a: string;
    }>("/me"),

  logout: () => request<void>("/logout", { method: "POST" }),
};
