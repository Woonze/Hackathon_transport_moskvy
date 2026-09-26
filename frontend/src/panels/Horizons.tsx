import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, LabelList, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, getJson, monthLabel, useDebounced } from './shared'
import type { RouteId } from './shared'
import './panels.css'

type Source = 'fact' | 'forecast' | 'scenario'
type YearRow = { route: number; month: string; passengers: number; source: Source }
type YearResponse = { note: string; growth: number; data: YearRow[] }
type Cell = { month: string; label: string; value: number; source: Source; fact?: number; forecast?: number; scenario?: number }

const NAMES: Record<Source, string> = { fact: 'Факт', forecast: 'Прогноз модели', scenario: 'Сценарий 2026' }
const ACCENT: Record<Source, string> = { fact: '#8fb0ff', forecast: '#7fa0ff', scenario: '#f0a339' }
const FILL: Record<Source, string> = { fact: '#4f75f3', forecast: 'url(#hzForecast)', scenario: 'url(#hzScenario)' }
const MONTH_NAMES = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const monthName = (ym: string) => `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`
const HINT_MONTH = 'Месяц — сумма посадок за календарный месяц. Сплошные столбцы — фактические данные января–октября, штриховые — прогноз модели на ноябрь–декабрь. Изменение считается к предыдущему месяцу.'

const compact = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2).replace('.', ',')}М` : n >= 1000 ? `${Math.round(n / 1000)}к` : String(Math.round(n)))
const signed = (a: number, b: number) => {
  if (!b) return '—'
  const delta = (a / b - 1) * 100
  if (Math.abs(delta) < 0.05) return '• без изменений'
  return `${delta > 0 ? '▲ +' : '▼ −'}${Math.abs(delta).toFixed(1).replace('.', ',')} %`
}

export default function Horizons({ route }: { route: RouteId }) {
  const [tab, setTab] = useState<'month' | 'year'>('month')
  const [growth, setGrowth] = useState(1)
  const [resp, setResp] = useState<YearResponse | null>(null)
  const [error, setError] = useState('')
  const g = useDebounced(growth)

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    getJson<YearResponse>(`/api/v1/forecast/year?growth=${g}${route === 'all' ? '' : `&route=${route}`}`, controller.signal)
      .then(setResp)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [route, g])

  const chart = useMemo<Cell[]>(() => {
    const byMonth = new Map<string, Cell>()
    for (const r of resp?.data ?? []) {
      if (tab === 'month' && !r.month.startsWith('2025')) continue
      const cell = byMonth.get(r.month) ?? { month: r.month, label: monthLabel(r.month), value: 0, source: r.source }
      cell[r.source] = (cell[r.source] ?? 0) + r.passengers
      cell.value += r.passengers
      cell.source = r.source
      byMonth.set(r.month, cell)
    }
    return [...byMonth.values()].sort((a, b) => a.month.localeCompare(b.month))
  }, [resp, tab])

  const at = (m: string) => chart.find((c) => c.month === m)?.value ?? 0
  const oct = at('2025-10'), nov = at('2025-11'), dec = at('2025-12')
  const facts = chart.filter((c) => c.source === 'fact')
  const factAverage = facts.length ? facts.reduce((s, c) => s + c.value, 0) / facts.length : 0
  const best = chart.filter((c) => c.month.startsWith('2025')).reduce<Cell | null>((top, c) => (!top || c.value > top.value ? c : top), null)
  const sum2026 = (resp?.data ?? []).filter((r) => r.source === 'scenario').reduce((s, r) => s + r.passengers, 0)
  const sum2025 = (resp?.data ?? []).filter((r) => r.month.startsWith('2025')).reduce((s, r) => s + r.passengers, 0)

  const range = (source: Source) => { const items = chart.filter((c) => c.source === source); return items.length ? { first: items[0].label, last: items[items.length - 1].label } : null }
  const factRange = range('fact'), forecastRange = range('forecast'), scenarioRange = tab === 'year' ? range('scenario') : null
  const sources = (tab === 'year' ? ['fact', 'forecast', 'scenario'] : ['fact', 'forecast']) as Source[]

  const tip = ({ active, payload }: { active?: boolean; payload?: { payload?: Cell }[] }) => {
    const item = active && payload?.length ? payload[0].payload : undefined
    if (!item) return null
    const index = chart.findIndex((c) => c.month === item.month)
    const previous = index > 0 ? chart[index - 1].value : 0
    return <div className="hz-tip"><b>{monthName(item.month)}</b><span style={{ color: ACCENT[item.source] }}>{NAMES[item.source]}</span><strong>{fmt(item.value)} посадок</strong>{previous > 0 && <em>{signed(item.value, previous)} к предыдущему месяцу</em>}</div>
  }

  return (
    <section className="x-section">
      <article className="panel x-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-title hz-title">Горизонты прогноза: месяц и год
              <span className="hz-info" tabIndex={0} role="note" aria-label="Пояснение к графику"><i>i</i><span className="hz-info-text">{tab === 'month' ? HINT_MONTH : (resp?.note ?? 'Год: 2025 — десять месяцев факта плюс прогноз, 2026 — сценарий по сезонному профилю.')}</span></span>
            </div>
            <div className="panel-subtitle">{route === 'all' ? 'Все маршруты' : `Трамвай ${route}`} · факт, прогноз модели и сценарий</div>
          </div>
          <div className="segmented"><button className={tab === 'month' ? 'active' : ''} onClick={() => setTab('month')}>Месяц</button><button className={tab === 'year' ? 'active' : ''} onClick={() => setTab('year')}>Год</button></div>
        </div>
        {error && <div className="x-error">{error}</div>}
        <div className="x-kpis hz-kpis">
          {tab === 'month' ? (
            <>
              <div><span>Ноябрь 2025 · прогноз</span><b>{fmt(nov)}</b><small>{signed(nov, oct)} к октябрю (факт)</small></div>
              <div><span>Декабрь 2025 · прогноз</span><b>{fmt(dec)}</b><small>{signed(dec, nov)} к ноябрю</small></div>
              <div><span>Максимум 2025</span><b>{best ? fmt(best.value) : '—'}</b><small>{best ? `${monthName(best.month)} · ${NAMES[best.source].toLowerCase()}` : '—'}</small></div>
              <div><span>Среднее за месяц · факт</span><b>{fmt(factAverage)}</b><small>январь–октябрь 2025</small></div>
            </>
          ) : (
            <>
              <div><span>2025 · факт и прогноз</span><b>{fmt(sum2025)}</b><small>10 мес. факта + 2 мес. прогноза</small></div>
              <div><span>2026 · сценарий</span><b>{fmt(sum2026)}</b><small>рост спроса ×{growth.toFixed(2)}</small></div>
              <div><span>2026 к 2025</span><b>{signed(sum2026, sum2025)}</b><small>по сценарию, не прогноз модели</small></div>
            </>
          )}
        </div>
        {tab === 'year' && (
          <div className="x-controls"><label className="x-field">Рост спроса в 2026: <b>×{growth.toFixed(2)}</b><input type="range" min={0.5} max={1.5} step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} /></label></div>
        )}
        <div className="x-chart hz-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 22, right: 8, left: -6, bottom: 0 }}>
              <defs>
                <pattern id="hzForecast" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="#4f75f333" /><rect width="3" height="7" fill="#4f75f3" /></pattern>
                <pattern id="hzScenario" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="#f0a33933" /><rect width="3" height="7" fill="#f0a339" /></pattern>
              </defs>
              <CartesianGrid stroke="#1b2b3b" vertical={false} />
              {forecastRange && <ReferenceArea x1={forecastRange.first} x2={forecastRange.last} fill="#4f75f3" fillOpacity={0.08} stroke="#4f75f388" strokeDasharray="4 4" label={{ value: 'Прогноз модели', position: 'insideTopLeft', fill: '#8fb0ff', fontSize: 11, fontWeight: 700 }} ifOverflow="visible" />}
              {scenarioRange && <ReferenceArea x1={scenarioRange.first} x2={scenarioRange.last} fill="#f0a339" fillOpacity={0.05} stroke="#f0a33955" strokeDasharray="4 4" label={{ value: 'Сценарий 2026', position: 'insideTopLeft', fill: '#f5b968', fontSize: 11, fontWeight: 700 }} ifOverflow="visible" />}
              {factRange && <ReferenceArea x1={factRange.first} x2={factRange.last} fill="transparent" stroke="transparent" label={{ value: 'Факт', position: 'insideTopLeft', fill: '#a9b6d3', fontSize: 11, fontWeight: 700 }} ifOverflow="visible" />}
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} interval={0} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} tickFormatter={compact} />
              <Tooltip content={tip} cursor={{ fill: '#ffffff0d' }} />
              {sources.map((k) => (
                <Bar key={k} dataKey={k} stackId="s" fill={FILL[k]} stroke={k === 'fact' ? undefined : ACCENT[k]} strokeWidth={k === 'fact' ? 0 : 1} radius={[3, 3, 0, 0]}>
                  {tab === 'month' && <LabelList dataKey={k} position="top" fill="#ffffff" fontSize={11} fontWeight={700} formatter={(v: unknown) => (typeof v === 'number' && v > 0 ? compact(v) : '')} />}
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="hz-legend">{sources.map((k) => <span key={k}><i className={`hz-swatch hz-${k}`} />{NAMES[k]}</span>)}</div>
      </article>
    </section>
  )
}
