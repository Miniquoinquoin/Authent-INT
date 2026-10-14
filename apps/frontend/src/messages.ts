/**
 * Every error sentence the user can read, chosen by US from a code (learning-plan, frontend
 * "Pièges"): never a server string, never `?error_description=` from a URL, never anything
 * that says whether an account exists.
 */
import type { ApiErrorCode } from './api/client'
import type { OidcErrorCode } from './auth/oidc'

export const EXPIRED = 'Ce lien de connexion a expiré. Recommencez depuis le portail.'

export const API_ERRORS: Record<ApiErrorCode, string> = {
  // Same sentence for a wrong number and a wrong password: the server makes them identical too
  invalid_credentials: 'Numéro fiscal ou mot de passe incorrect.',
  account_locked:
    'Votre compte est temporairement verrouillé après plusieurs échecs. Réessayez plus tard ou réinitialisez votre mot de passe.',
  too_many_attempts: 'Trop de tentatives. Patientez une minute avant de réessayer.',
  unknown_interaction: EXPIRED,
  login_required: EXPIRED,
  invalid_token: 'Ce lien est invalide, a expiré ou a déjà été utilisé. Demandez-en un nouveau.',
  validation: 'Les informations saisies ne sont pas valides.',
  network: 'Le service est momentanément injoignable. Vérifiez votre connexion et réessayez.',
  unexpected: 'Une erreur inattendue est survenue. Réessayez plus tard.',
}

export const OIDC_ERRORS: Record<OidcErrorCode, string> = {
  access_denied: "Vous avez refusé l'accès : vous n'êtes pas connecté au portail.",
  state_mismatch: "La réponse de connexion ne correspond à aucune demande de cet onglet. Recommencez la connexion.",
  nonce_mismatch: "La réponse de connexion n'a pas pu être vérifiée. Recommencez la connexion.",
  invalid_id_token: "La réponse de connexion n'a pas pu être vérifiée. Recommencez la connexion.",
  missing_code: "La réponse de connexion est incomplète. Recommencez la connexion.",
  token_exchange_failed: 'La connexion a expiré ou a déjà été utilisée. Recommencez la connexion.',
  network: API_ERRORS.network,
  invalid_request: 'La demande de connexion est invalide. Recommencez la connexion.',
  unauthorized_client: "Ce portail n'est pas autorisé à vous connecter. Contactez l'assistance.",
  unsupported_response_type: 'La demande de connexion est invalide. Recommencez la connexion.',
  invalid_scope: 'La demande de connexion est invalide. Recommencez la connexion.',
  server_error: 'Le service de connexion a rencontré une erreur. Réessayez plus tard.',
  temporarily_unavailable: 'Le service de connexion est momentanément indisponible. Réessayez plus tard.',
}

export const NUMERO_FISCAL_FORMAT = 'Le numéro fiscal comporte exactement 13 chiffres.'
