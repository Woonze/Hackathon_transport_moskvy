import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, getJson, monthLabel, useDebounced } from './shared'
import type { RouteId } from './shared'
import './panels.css'

type YearRow = { route: number; month: string; passengers: number; source: 'fact' | 'forecast' | 'scenario' }
type YearResponse = { note: string; growth: number; data: YearRow[] }
const NAMES = { fact: 'Факт', forecast: 'Прогноз модели', scenario: 'Сценарий 2026' } as const
const COLORS = { fact: '#a9b6d3', forecast: '#4f75f3', scenario: '#f0a339' } as const

export default function Horizons({ route }: { route: RouteId }) {
  const [tab, setTab] = useState<'month' | 'year'>('month')
  const [growth, setGrowth] = useState(1)
  const [resp, setResp] = useState<YearResponse | null>(null)
  const [error, setError] = useState('')
  const g = useDebounced(growth)

  useEffect(() => {
    setError('')
    getJson<YearResponse>(`/api/v1/forecast/year?growth=${g}${route === 'all' ? '' : `&route=${route}`}`).then(setResp).catch((e: Error) => setError(e.message))
  }, [route, g])

  const chart = useMemo(() => {
    const byMonth = new Map<string, Record<string, string | number>>()
    for (const r of resp?.data ?? []) {
      if (tab === 'month' && !r.month.startsWith('2025')) continue
      const cell = byMonth.get(r.month) ?? { month: r.month, label: monthLabel(r.month) }
      cell[r.source] = ((cell[r.source] as number) ?? 0) + r.passengers
      byMonth.set(r.month, cell)
    }
    return [...byMonth.values()].sort((a, b) => String(a.month).localeCompare(String(b.month)))
  }, [resp, tab])

  const total = (m: string) => Number(chart.find((c) => c.month === m)?.forecast ?? 0)
  const oct = Number(chart.find((c) => c.month === '2025-10')?.fact ?? 0)
  const nov = total('2025-11'), dec = total('2025-12')
  const sum2026 = (resp?.data ?? []).filter((r) => r.source === 'scenario').reduce((s, r) => s + r.passengers, 0)
  const sum2025 = (resp?.data ?? []).filter((r) => r.month.startsWith('2025')).reduce((s, r) => s + r.passengers, 0)
  const pct = (a: number, b: number) => (b ? `${a >= b ? '+' : ''}${((a / b - 1) * 100).toFixed(1)}%` : '—')

  return (
    <section className="x-section">
      <article className="panel x-panel">
        <div className="panel-heading">
          <div><div className="panel-title">Горизонты прогноза: месяц и год</div><div className="panel-subtitle">{route === 'all' ? 'Все маршруты' : `Трамвай ${route}`} · факт, прогноз модели и сценарий</div></div>
          <div className="segmented"><button className={tab === 'month' ? 'active' : ''} onClick={() => setTab('month')}>Месяц</button><button className={tab === 'year' ? 'active' : ''} onClick={() => setTab('year')}>Год</button></div>
        </div>
        {error && <div className="x-error">{error}</div>}
        <div className="x-kpis">
          {tab === 'month' ? (
            <>
              <div><b>{fmt(nov)}</b><span>прогноз на ноябрь 2025</span></div>
              <div><b>{fmt(dec)}</b><span>прогноз на декабрь 2025</span></div>
              <div><b className={nov >= oct ? 'up' : 'down'}>{pct(nov, oct)}</b><span>ноябрь к октябрю (факт)</span></div>
              <div><b className={dec >= nov ? 'up' : 'down'}>{pct(dec, nov)}</b><span>декабрь к ноябрю</span></div>
            </>
          ) : (
            <>
              <div><b>{fmt(sum2025)}</b><span>2025: 10 мес. факта + 2 мес. прогноза</span></div>
              <div><b>{fmt(sum2026)}</b><span>сценарий 2026 (рост ×{growth.toFixed(2)})</span></div>
              <div><b className={sum2026 >= sum2025 ? 'up' : 'down'}>{pct(sum2026, sum2025)}</b><span>2026 к 2025</span></div>
            </>
          )}
        </div>
        {tab === 'year' && (
          <div className="x-controls"><label className="x-field">Рост спроса в 2026: <b>×{growth.toFixed(2)}</b><input type="range" min={0.5} max={1.5} step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} /></label></div>
        )}
        <div className="x-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 8, left: -6, bottom: 0 }}>
              <CartesianGrid stroke="#edf0f6" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} interval={0} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} tickFormatter={(n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}М` : n >= 1000 ? `${Math.round(n / 1000)}к` : n)} />
              <Tooltip formatter={(v, n) => [`${fmt(Number(v))} посадок`, NAMES[n as keyof typeof NAMES] ?? n]} contentStyle={{ borderRadius: 10, fontSize: 12 }} />
              <Legend formatter={(n) => NAMES[n as keyof typeof NAMES] ?? n} wrapperStyle={{ fontSize: 11 }} />
              {(Object.keys(NAMES) as (keyof typeof NAMES)[]).filter((k) => tab === 'year' || k !== 'scenario').map((k) => <Bar key={k} dataKey={k} stackId="s" fill={COLORS[k]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
        {resp && tab === 'year' && <div className="x-note">{resp.note}</div>}
        {tab === 'month' && <div className="x-note">Месяц — сумма посадок за календарный месяц. Серые столбцы — фактические данные января–октября, синие — прогноз модели на ноябрь–декабрь.</div>}
      </article>
    </section>
  )
}
