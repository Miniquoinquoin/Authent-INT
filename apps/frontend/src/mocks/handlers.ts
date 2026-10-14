/**
 * The fake auth-server of lane B5 (ADR §17: "Démarre contre: Mock OpenAPI (MSW)").
 * Response shapes are typed from the generated OpenAPI (src/api/types.ts): if the
 * contract changes, the mock stops compiling instead of silently lying.
 */
import type { RequestHandler } from 'msw'

export const handlers: RequestHandler[] = []
