import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { fmt, getJson, pad, useDebounced } from './shared'
import type { RouteId } from './shared'
import './panels.css'

type Hour = { hour: number; boardings: number; share: number; typical: number; index: number | null; level: string; load?: number; vehicles_needed?: number; vehicles_delta?: number; load_level?: string }
type Hotspot = { hour: number; direction: number; from: string; to: string; passengers: number }
type Plan = { date: string; weekday: string; day_total: number; hours: Hour[]; peaks: { hours: number[]; share: number; peak_to_mean: number | null }; hotspots: Hotspot[] | null; vehicles?: { overloaded_hours: number[] } }
type Saving = { route: number; date: string; weekday: string; base: number; corrected: number; delta: number; reasons: string[] }
type Savings = { total_days: number; total_delta: number; share_of_forecast: number; days: Saving[] }

const LEVEL_COLOR: Record<string, string> = { 'пик': '#e65f73', 'выше обычного': '#f0a339', 'ниже обычного': '#a9b6d3', 'обычно': '#4f75f3', 'нет движения': '#dfe4ee' }
const LOAD_CLASS: Record<string, string> = { 'перегрузка': 'x-badge-red', 'норма': 'x-badge-blue', 'запас': 'x-badge-grey' }
const dm = (iso: string) => `${iso.slice(8)}.${iso.slice(5, 7)}`

export default function Dispatch({ route: dashboardRoute }: { route: RouteId }) {
  const [route, setRoute] = useState<RouteId>(7)
  const [date, setDate] = useState('2025-11-10')
  const [corrOn, setCorrOn] = useState(true)
  const [capacity, setCapacity] = useState('')
  const [vehicles, setVehicles] = useState('')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [savings, setSavings] = useState<Savings | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { setRoute(dashboardRoute) }, [dashboardRoute])
  const query = useDebounced(useMemo(() => {
    const q = new URLSearchParams({ date, corrections: corrOn ? 'calendar,regime' : '' })
    if (route !== 'all') q.set('route', String(route))
    const cap = Number(capacity), veh = Number(vehicles)
    if (route !== 'all' && cap > 0 && Number.isInteger(veh) && veh >= 1) { q.set('capacity', String(cap)); q.set('vehicles', String(veh)) }
    return q.toString()
  }, [route, date, corrOn, capacity, vehicles]), 300)

  useEffect(() => {
    const controller = new AbortController()
    getJson<Plan>(`/api/v1/dispatch/day?${query}`, controller.signal).then((p) => { setPlan(p); setError('') })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [query])
  useEffect(() => {
    const controller = new AbortController()
    getJson<Savings>(`/api/v1/dispatch/savings?limit=8${route === 'all' ? '' : `&route=${route}`}`, controller.signal).then(setSavings)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [route])

  const rows = (plan?.hours ?? []).filter((h) => h.boardings > 0 || h.typical > 0)
  const withVehicles = rows.some((h) => h.load !== undefined)
  const chart = (plan?.hours ?? []).map((h) => ({ label: `${pad(h.hour)}`, boardings: h.boardings, level: h.level }))
  return (
    <section className="x-section">
      <article className="panel x-panel">
        <div className="panel-heading">
          <div><div className="panel-title">Сводка диспетчера на день</div><div className="panel-subtitle">Пиковые часы, отклонения от обычного дня, горячие участки, расчёт нехватки вагонов и дни для пересмотра выпуска</div></div>
        </div>
        <div className="x-controls">
          <label className="x-field">Маршрут<select value={route} onChange={(e) => setRoute(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
            <option value="all">Все маршруты</option>{[1, 5, 7, 11, 12, 17, 25, 26, 28, 50].map((r) => <option key={r} value={r}>Трамвай {r}</option>)}</select></label>
          <label className="x-field">Дата<input type="date" min="2025-11-01" max="2025-12-31" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} /></label>
          <label className="x-check"><input type="checkbox" checked={corrOn} onChange={(e) => setCorrOn(e.target.checked)} /> Учесть календарь и сдвиги режима</label>
          <label className="x-field">Посадок за час на один вагон<input type="number" min={1} placeholder="задаёт диспетчер" value={capacity} onChange={(e) => setCapacity(e.target.value)} disabled={route === 'all'} /></label>
          <label className="x-field">Вагонов на линии<input type="number" min={1} step={1} placeholder="число вагонов" value={vehicles} onChange={(e) => setVehicles(e.target.value)} disabled={route === 'all'} /></label>
        </div>
        {error && <div className="x-error">{error}</div>}
        {plan && (
          <>
            <div className="x-kpis">
              <div><b>{fmt(plan.day_total)}</b><span>посадок за {plan.weekday}, {dm(plan.date)}</span></div>
              <div><b>{plan.peaks.hours.map((h) => `${pad(h)}:00`).join(', ')}</b><span>пиковые часы: {(plan.peaks.share * 100).toFixed(1)}% суточных посадок{plan.peaks.peak_to_mean ? `, пик в ${plan.peaks.peak_to_mean.toFixed(2)} раза выше среднего` : ''}</span></div>
              {plan.vehicles && <div><b>{plan.vehicles.overloaded_hours.length ? plan.vehicles.overloaded_hours.map((h) => `${pad(h)}:00`).join(', ') : 'нет'}</b><span>часы с перегрузкой при заданных вагонах</span></div>}
            </div>
            <div className="x-split">
              <div>
                <div className="x-chart" style={{ height: 230 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chart} margin={{ top: 8, right: 6, left: -12, bottom: 0 }}>
                      <CartesianGrid stroke="#edf0f6" vertical={false} />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} interval={1} />
                      <YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} />
                      <ChartTooltip formatter={(v, _n, item) => [`${fmt(Number(v))} посадок`, (item.payload as { level: string }).level]} labelFormatter={(l) => `${l}:00`} contentStyle={{ borderRadius: 10, fontSize: 12 }} />
                      <Bar dataKey="boardings" radius={[3, 3, 0, 0]} isAnimationActive={false}>{chart.map((c) => <Cell key={c.label} fill={LEVEL_COLOR[c.level] ?? '#4f75f3'} />)}</Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="x-legend">{Object.entries(LEVEL_COLOR).filter(([k]) => k !== 'нет движения').map(([k, c]) => <span key={k}><i className="x-swatch" style={{ background: c }} /> {k}</span>)}</div>
                {plan.hotspots && plan.hotspots.length > 0 && (
                  <div className="x-note"><b>Горячие участки (оценка):</b> {plan.hotspots.map((s) => `${pad(s.hour)}:00 «${s.from}» → «${s.to}» ~${fmt(s.passengers)}`).join(' · ')}</div>
                )}
                {plan.hotspots === null && <div className="x-note">Горячие участки считаются для одного маршрута с остановками в справочнике: 1, 5, 7, 11, 12.</div>}
              </div>
              <div className="x-scroll">
                <table className="x-table">
                  <thead><tr><th>Час</th><th>Посадки</th><th>К обычному</th><th>Оценка</th>{withVehicles && <><th>Загрузка</th><th>Вагонов нужно</th></>}</tr></thead>
                  <tbody>{rows.map((h) => (
                    <tr key={h.hour}><td>{pad(h.hour)}:00</td><td>{fmt(h.boardings)}</td><td>{h.index === null ? '—' : `${Math.round(h.index * 100)}%`}</td>
                      <td><span className="x-badge" style={{ background: LEVEL_COLOR[h.level] + '33', color: '#29354a' }}>{h.level}</span></td>
                      {withVehicles && <><td><span className={`x-badge ${LOAD_CLASS[h.load_level ?? 'норма']}`}>{Math.round((h.load ?? 0) * 100)}% · {h.load_level}</span></td><td>{h.vehicles_needed} ({(h.vehicles_delta ?? 0) > 0 ? '+' : ''}{h.vehicles_delta})</td></>}
                    </tr>))}</tbody>
                </table>
              </div>
            </div>
          </>
        )}
        {savings && (
          <div className="x-note" style={{ marginTop: 14 }}>
            <b>Дни с пониженным спросом, где возможен пересмотр выпуска:</b> {savings.total_days} дн., прогноз с поправками ниже прогноза модели на {fmt(savings.total_delta)} посадок ({(savings.share_of_forecast * 100).toFixed(1)}% периода). Больше всего:
            {' '}{savings.days.map((d) => `${dm(d.date)} маршрут ${d.route} (−${fmt(d.delta)}, ${d.reasons.join(', ')})`).join(' · ')}.
            {' '}Это оценка по прогнозу, не измеренная экономия.
          </div>
        )}
        <div className="x-note">Расчёт вагонов использует значения, которые вводит диспетчер: в справочнике вместимость задана только классом (ОБК, БК). Уровни «выше» и «ниже обычного» — отклонение от среднего того же дня недели без праздников (порог ±15%).</div>
      </article>
    </section>
  )
}
