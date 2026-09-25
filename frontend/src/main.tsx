import React, { lazy, Suspense, useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

const Tester = lazy(() => import('./Tester'))
const Stands = lazy(() => import('./Stands'))

// Страница проверки API открывается по /#/tester
function Root() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  if (hash.startsWith('#/tester')) return <Suspense fallback={<div className="loading-card">Загружаем проверку API…</div>}><Tester /></Suspense>
  if (hash.startsWith('#/stands')) return <Suspense fallback={<div className="stands-loading">Загружаем UX-макеты…</div>}><Stands /></Suspense>
  return <App />
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Root /></React.StrictMode>,
)
