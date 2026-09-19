import { BrowserRouter, Routes, Route } from 'react-router'
import Login from './Login'
import ProtectedPage from './Protected'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/protected" element={<ProtectedPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
