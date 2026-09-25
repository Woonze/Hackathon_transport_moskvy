import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import Login from './Login'

const Tester = lazy(() => import('./Tester'))
const API = import.meta.env.VITE_API_URL ?? ''

// Страница проверки API открывается по /#/tester
function Root() {
  const [hash, setHash] = useState(window.location.hash)
  const [username, setUsername] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)
  const [connectionError, setConnectionError] = useState('')
  const [authRevision, setAuthRevision] = useState(0)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  useEffect(() => {
    let cancelled = false
    setChecking(true)
    fetch(`${API}/api/auth/me`, { credentials: 'same-origin', cache: 'no-store' })
      .then(async (r) => {
        if (r.ok) return (await r.json()).username as string
        if (r.status === 401) return null
        throw new Error('Сервис авторизации временно недоступен')
      })
      .then((name) => { if (!cancelled) { setUsername(name); setConnectionError('') } })
      .catch(() => { if (!cancelled) { setUsername(null); setConnectionError('Не удалось подключиться к сервису. Проверьте соединение и попробуйте ещё раз.') } })
      .finally(() => { if (!cancelled) setChecking(false) })
    return () => { cancelled = true }
  }, [authRevision])

  const logout = useCallback(async () => {
    await fetch(`${API}/api/auth/logout`, { method: 'POST', credentials: 'same-origin' }).catch(() => undefined)
    setUsername(null)
  }, [])

  if (checking) return <div className="auth-loading"><span className="loader" /> Проверяем доступ…</div>
  if (!username) return <Login error={connectionError} onRetry={() => setAuthRevision((value) => value + 1)} onLogin={setUsername} />
  return hash.startsWith('#/tester')
    ? <Suspense fallback={<div className="loading-card">Загружаем проверку API…</div>}><Tester username={username} onLogout={logout} /></Suspense>
    : <App username={username} onLogout={logout} />
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Root /></React.StrictMode>,
)
