import type { ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { ChoosePassword } from './pages/account/ChoosePassword'
import { RequestLink } from './pages/account/RequestLink'
import Callback from './pages/Callback'
import Login from './pages/login/Login'
import NotFound from './pages/NotFound'
import Portal from './pages/Portal'

/**
 * Routes. /login, /activate and /reset-password are fixed by the auth-server: it redirects to
 * `${ISSUER}/login?uid=…` (Caddy serves this SPA there too, so the session cookie is first-party) and mails `/activate?token=…`, `/reset-password?token=…`.
 * /callback is portail-web's registered redirect_uri. `extra` is how the mock mode adds its
 * fake /authorize (src/mocks/browser.tsx) without the routes existing in a real build.
 */
export default function App({ extra }: { extra?: ReactNode }) {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Portal />} />
        <Route path="/callback" element={<Callback />} />
        <Route path="/login" element={<Login />} />
        <Route path="/activation" element={<RequestLink kind="activation" />} />
        <Route path="/activate" element={<ChoosePassword kind="activation" />} />
        <Route path="/mot-de-passe-oublie" element={<RequestLink kind="reset" />} />
        <Route path="/reset-password" element={<ChoosePassword kind="reset" />} />
        {extra}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}
