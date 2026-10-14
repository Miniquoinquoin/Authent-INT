import { describe, expect, it } from 'vitest'
import { base64url, challengeS256, randomToken } from './pkce'

describe('PKCE', () => {
  it('matches the RFC 7636 Appendix B test vector', async () => {
    await expect(challengeS256('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).resolves.toBe(
      'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
    )
  })

  it('makes verifiers of 43 unreserved characters (RFC 7636 §4.1: 43 to 128)', () => {
    for (let i = 0; i < 50; i++) {
      expect(randomToken()).toMatch(/^[A-Za-z0-9\-_]{43}$/)
    }
  })

  it('never repeats a verifier', () => {
    const seen = new Set(Array.from({ length: 200 }, randomToken))
    expect(seen.size).toBe(200)
  })

  it('encodes base64url without padding', () => {
    expect(base64url(new Uint8Array([0xfb, 0xff]))).toBe('-_8')
  })
})
