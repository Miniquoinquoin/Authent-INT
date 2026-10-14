import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

async function boot() {
  let extra: ReactNode = null
  // `vite --mode mock` only: in any other build this branch is dead code and the mocks are not bundled
  if (import.meta.env.MODE === 'mock') {
    const { startMockWorker, mockRoutes } = await import('./mocks/browser')
    await startMockWorker() // before the first render: /callback's /token call must be intercepted
    extra = mockRoutes
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App extra={extra} />
    </StrictMode>,
  )
}

void boot()
