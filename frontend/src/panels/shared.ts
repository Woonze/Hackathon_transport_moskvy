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

export const getJson = <T,>(url: string): Promise<T> => fetch(API + url).then((r) => parse<T>(r))
export const postJson = <T,>(url: string, body: unknown): Promise<T> =>
  fetch(API + url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => parse<T>(r))

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export const lastDay = (year: number, month: number) => new Date(year, month, 0).getDate()
export const pad = (n: number) => String(n).padStart(2, '0')
