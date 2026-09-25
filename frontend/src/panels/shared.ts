import { useEffect, useState } from 'react'

export const API = import.meta.env.VITE_API_URL ?? ''
export const fmt = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))
export type RouteId = 'all' | number

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
export const monthLabel = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`

async function parse<T>(r: Response): Promise<T> {
  const body = await r.json().catch(() => null)
  if (!r.ok) throw new Error(body?.detail ?? `Ошибка сервера (${r.status})`)
  return body as T
}

export const getJson = <T,>(url: string, signal?: AbortSignal): Promise<T> =>
  fetch(API + url, signal ? { signal } : undefined).then((r) => parse<T>(r))
export const postJson = <T,>(url: string, body: unknown, signal?: AbortSignal): Promise<T> =>
  fetch(API + url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }).then((r) => parse<T>(r))

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export const lastDay = (year: number, month: number) => new Date(year, month, 0).getDate()
export const pad = (n: number) => String(n).padStart(2, '0')

export type LiveEvent = { version: string; history_end: string; ingested_boardings: number; updated_at: string; worker_pid: number; ml_model: { name: string; version: string; training_rows: number; duration_ms: number; updated_at: string; updates: number; pending_boardings: number; calendar_in_model: boolean } }
export type LiveState = { status: 'off' | 'connecting' | 'online' | 'offline'; last: LiveEvent | null; events: number; receivedAt: Date | null }

// Подписка на SSE /api/v1/stream: событие update приходит при подключении и при каждом приёме новых валидаций.
export function useLive(enabled: boolean, onEvent?: (e: LiveEvent) => void): LiveState {
  const [state, setState] = useState<LiveState>({ status: 'off', last: null, events: 0, receivedAt: null })
  useEffect(() => {
    if (!enabled) { setState((s) => ({ ...s, status: 'off' })); return }
    setState((s) => ({ ...s, status: 'connecting' }))
    const es = new EventSource(API + '/api/v1/stream')
    es.onopen = () => setState((s) => ({ ...s, status: 'online' }))
    es.onerror = () => setState((s) => ({ ...s, status: 'offline' })) // EventSource переподключается сам
    es.addEventListener('update', (m) => {
      const e = JSON.parse((m as MessageEvent).data) as LiveEvent
      setState((s) => ({ status: 'online', last: e, events: s.events + 1, receivedAt: new Date() }))
      onEvent?.(e)
    })
    return () => es.close()
  }, [enabled]) // eslint-disable-line react-hooks/exhaustive-deps
  return state
}
