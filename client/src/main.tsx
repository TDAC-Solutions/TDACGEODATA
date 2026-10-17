import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// CSS imports are resolved by the bundler; moduleResolution is "bundler".
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <App/>
    </AuthProvider>
  </StrictMode>,
);
