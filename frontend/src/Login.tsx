import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, LockKeyhole, TramFront } from 'lucide-react'
import './login.css'

const API = import.meta.env.VITE_API_URL ?? ''

export default function Login({ onLogin, error, onRetry }: { onLogin: (username: string) => void; error: string; onRetry: () => void }) {
  const [username, setUsername] = useState('fotur')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState(error)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage('')
    setSubmitting(true)
    try {
      const response = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const body = await response.json().catch(() => ({})) as { username?: string; detail?: string }
      if (!response.ok || !body.username) throw new Error(body.detail || 'Не удалось войти. Проверьте логин и пароль.')
      setPassword('')
      onLogin(body.username)
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Не удалось подключиться к сервису')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-page">
    <div className="login-decoration login-decoration-one" /><div className="login-decoration login-decoration-two" />
    <section className="login-card">
      <div className="login-brand"><div className="login-logo"><TramFront size={23} /></div><div><b>МОС.ТРАМ</b><span>АНАЛИТИКА ПАССАЖИРОПОТОКА</span></div></div>
      <div className="login-intro"><div className="login-eyebrow"><span /> ЕДИНЫЙ ДИСПЕТЧЕРСКИЙ ЦЕНТР</div><h1>Вход в систему</h1><p>Авторизуйтесь, чтобы открыть аналитику и прогнозы маршрутов.</p></div>
      <form onSubmit={submit}>
        <label>Логин<div className="login-input"><span>@</span><input autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required /></div></label>
        <label>Пароль<div className="login-input"><LockKeyhole size={17} /><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div></label>
        {message && <div className="login-error" role="alert">{message}</div>}
        {error && <button className="login-retry" type="button" onClick={onRetry}>Повторить подключение</button>}
        <button className="login-submit" type="submit" disabled={submitting}>{submitting ? 'Проверяем…' : <>Войти в систему <ArrowRight size={17} /></>}</button>
      </form>
      <div className="login-foot"><span className="login-shield"><LockKeyhole size={13} /></span> Доступ предоставляется администратором</div>
    </section>
    <div className="login-caption">МОСКОВСКИЙ ГОРОДСКОЙ ТРАНСПОРТ <i /> СИСТЕМА ОПЕРАТИВНОЙ АНАЛИТИКИ</div>
  </main>
}
