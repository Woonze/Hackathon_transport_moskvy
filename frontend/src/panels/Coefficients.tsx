import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, getJson, lastDay, pad, postJson, useDebounced } from './shared'
import type { RouteId } from './shared'
import './panels.css'

type Preset = { label: string; value: number; measured?: boolean; ci95?: [number, number]; days?: number }
type Presets = { disclaimer: string; weather: Preset[]; event: Preset[]; season: Preset[]; sources: { calendar: string; weather: string }; calendar: { holiday_factor: number; holiday_effect_ci95: [number, number] | null; days: string[] } }
type Point = { route: number; date: string; passengers: number; base: number }
type Adjusted = { summary: { base_total: number; adjusted_total: number; delta: number; delta_pct: number | null; global_multiplier: number }; data: Point[] }
type Factors = { weather: number; event: number; season: number }
type Regime = { weeks: number; cells: { route: number; weekday_name: string; factor: number; recent_mean: number; history_mean: number }[] }
type WeatherInfo = { rain_factor: number | null; snow_factor: number | null; days: { date: string; factor: number; flags: string[] }[] }
const TITLES: Record<keyof Factors, string> = { weather: 'Погода', event: 'Событие', season: 'Сезон' }

export default function Coefficients({ route }: { route: RouteId }) {
  const [month, setMonth] = useState(12)
  const [factors, setFactors] = useState<Factors>({ weather: 1, event: 1, season: 1 })
  const [ruleOn, setRuleOn] = useState(false)
  const [regimeOn, setRegimeOn] = useState(false)
  const [weatherOn, setWeatherOn] = useState(false)
  const [regime, setRegime] = useState<Regime | null>(null)
  const [weatherInfo, setWeatherInfo] = useState<WeatherInfo | null>(null)
  const [rule, setRule] = useState({ from: 25, to: 31, hourFrom: 0, hourTo: 23, factor: 0.8 })
  const [presets, setPresets] = useState<Presets | null>(null)
  const [result, setResult] = useState<Adjusted | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getJson<Presets>('/api/v1/factors', controller.signal)
      .then(setPresets)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    getJson<Regime>('/api/v1/regime', controller.signal).then(setRegime).catch(() => undefined)
    return () => controller.abort()
  }, [])

  const days = lastDay(2025, month)
  useEffect(() => { getJson<WeatherInfo>(`/api/v1/weather?start=2025-${pad(month)}-01&end=2025-${pad(month)}-${pad(days)}`).then(setWeatherInfo).catch(() => setWeatherInfo(null)) }, [month, days])
  const body = useDebounced(useMemo(() => {
    const ym = `2025-${pad(month)}`
    const b: Record<string, unknown> = { start: `${ym}-01`, end: `${ym}-${pad(days)}`, granularity: 'day', factors, rules: [], regime: regimeOn, weather_auto: weatherOn }
    if (route !== 'all') b.route = route
    if (ruleOn) b.rules = [{ start: `${ym}-${pad(Math.min(rule.from, days))}`, end: `${ym}-${pad(Math.min(rule.to, days))}`, factor: rule.factor, hour_from: rule.hourFrom, hour_to: rule.hourTo, label: 'из интерфейса' }]
    return JSON.stringify(b)
  }, [month, days, factors, ruleOn, rule, route, regimeOn, weatherOn]), 300)

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    postJson<Adjusted>('/api/v1/forecast/adjusted', JSON.parse(body), controller.signal)
      .then(setResult)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [body])

  const chart = useMemo(() => {
    const byDate = new Map<string, { label: string; base: number; adjusted: number }>()
    for (const p of result?.data ?? []) {
      const c = byDate.get(p.date) ?? { label: p.date.slice(8) + '.' + p.date.slice(5, 7), base: 0, adjusted: 0 }
      c.base += p.base; c.adjusted += p.passengers
      byDate.set(p.date, c)
    }
    return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v)
  }, [result])

  const s = result?.summary
  const changed = factors.weather !== 1 || factors.event !== 1 || factors.season !== 1 || ruleOn || regimeOn || weatherOn
  const slider = (k: keyof Factors) => (
    <label className="x-field" key={k}>{TITLES[k]}: <b>×{factors[k].toFixed(2)}</b>
      <input type="range" min={0.5} max={1.5} step={0.05} value={factors[k]} onChange={(e) => setFactors({ ...factors, [k]: Number(e.target.value) })} />
    </label>
  )

  return (
    <section className="x-section">
      <article className="panel x-panel">
        <div className="panel-heading">
          <div><div className="panel-title">Корректирующие коэффициенты</div><div className="panel-subtitle">Поправка на погоду, событие и сезон — прогноз пересчитывается сразу · {route === 'all' ? 'все маршруты' : `трамвай ${route}`}</div></div>
          <div className="segmented"><button className={month === 11 ? 'active' : ''} onClick={() => setMonth(11)}>Ноябрь</button><button className={month === 12 ? 'active' : ''} onClick={() => setMonth(12)}>Декабрь</button></div>
        </div>
        <div className="x-controls">
          {(Object.keys(TITLES) as (keyof Factors)[]).map(slider)}
          <button className="secondary-button" onClick={() => { setFactors({ weather: 1, event: 1, season: 1 }); setRuleOn(false); setRegimeOn(false); setWeatherOn(false) }} disabled={!changed}>Сбросить</button>
        </div>
        {presets && (
          <div className="x-chips">
            {(Object.keys(TITLES) as (keyof Factors)[]).filter((k) => presets[k].length > 1).map((k) => (
              <span key={k} className="x-chips">{TITLES[k]}:{presets[k].map((p) => (
                <button key={p.label} className="x-chip" onClick={() => setFactors({ ...factors, [k]: p.value })}
                  title={p.measured ? `Измерено на данных 2025: ×${p.value}, 95% ДИ ×${p.ci95?.[0]}–×${p.ci95?.[1]}, ${p.days} дн.` : p.value === 1 ? 'Без поправки' : `×${p.value} — экспертная оценка, не проверялась на данных`}>
                  {p.measured ? '✓ ' : ''}{p.label}{p.value !== 1 ? ` ×${p.value}` : ''}
                </button>))}
              </span>
            ))}
          </div>
        )}
        {presets && presets.calendar.days.length > 0 && (
          <div className="x-controls">
            <span className="panel-subtitle" style={{ margin: 0, paddingBottom: 6 }}>
              Производственный календарь РФ уже учитывается ML-моделью. Праздничные будни: {presets.calendar.days.map((d) => `${Number(d.slice(8))}.${d.slice(5, 7)}`).join(', ')}. Измеренный эффект в истории: {((presets.calendar.holiday_factor - 1) * 100).toFixed(1)}%
              {presets.calendar.holiday_effect_ci95 ? ` (95% ДИ ${(presets.calendar.holiday_effect_ci95[0] * 100).toFixed(1)}…${(presets.calendar.holiday_effect_ci95[1] * 100).toFixed(1)}%)` : ''}
            </span>
          </div>
        )}
        {regime && regime.cells.length > 0 && (
          <div className="x-controls">
            <label className="x-check"><input type="checkbox" checked={regimeOn} onChange={(e) => setRegimeOn(e.target.checked)} /> Учесть сдвиги режима маршрутов</label>
            <span className="panel-subtitle" style={{ margin: 0, paddingBottom: 6 }}>
              Найдено автоматически (последние {regime.weeks} недель к средней за всю историю): {regime.cells.map((c) => `маршрут ${c.route}, ${c.weekday_name} ×${c.factor.toFixed(2)}`).join('; ')}
            </span>
          </div>
        )}
        {weatherInfo && (
          <div className="x-controls">
            <label className="x-check"><input type="checkbox" checked={weatherOn} onChange={(e) => setWeatherOn(e.target.checked)} /> Учесть погоду по архиву Open-Meteo</label>
            <span className="panel-subtitle" style={{ margin: 0, paddingBottom: 6 }}>
              Дней с осадками ≥ 5 мм или снегом ≥ 2 см в этом месяце: {weatherInfo.days.filter((d) => d.factor !== 1).length}
              {weatherInfo.rain_factor ? ` (осадки ×${weatherInfo.rain_factor.toFixed(3)}, снег ×${weatherInfo.snow_factor?.toFixed(3)})` : ''}. Это фактическая погода из архива, а не прогноз погоды.
            </span>
          </div>
        )}
        <div className="x-controls">
          <label className="x-check"><input type="checkbox" checked={ruleOn} onChange={(e) => setRuleOn(e.target.checked)} /> Точечное правило на дни и часы</label>
          {ruleOn && (
            <>
              <label className="x-field">С числа<input type="number" min={1} max={days} value={rule.from} onChange={(e) => setRule({ ...rule, from: Number(e.target.value) })} /></label>
              <label className="x-field">По число<input type="number" min={1} max={days} value={rule.to} onChange={(e) => setRule({ ...rule, to: Number(e.target.value) })} /></label>
              <label className="x-field">Час с<input type="number" min={0} max={23} value={rule.hourFrom} onChange={(e) => setRule({ ...rule, hourFrom: Number(e.target.value) })} /></label>
              <label className="x-field">Час по<input type="number" min={0} max={23} value={rule.hourTo} onChange={(e) => setRule({ ...rule, hourTo: Number(e.target.value) })} /></label>
              <label className="x-field">Множитель<input type="number" min={0.1} max={3} step={0.05} value={rule.factor} onChange={(e) => setRule({ ...rule, factor: Number(e.target.value) })} /></label>
            </>
          )}
        </div>
        {error && <div className="x-error">{error}</div>}
        {s && (
          <div className="x-kpis">
            <div><b>{fmt(s.base_total)}</b><span>прогноз модели</span></div>
            <div><b>{fmt(s.adjusted_total)}</b><span>с коэффициентами</span></div>
            <div><b className={s.delta >= 0 ? 'up' : 'down'}>{s.delta_pct === null ? '—' : `${s.delta >= 0 ? '+' : ''}${s.delta_pct}%`}</b><span>изменение ({s.delta >= 0 ? '+' : ''}{fmt(s.delta)})</span></div>
            <div><b>×{s.global_multiplier}</b><span>общий множитель</span></div>
          </div>
        )}
        <div className="x-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ top: 8, right: 8, left: -6, bottom: 0 }}>
              <CartesianGrid stroke="#edf0f6" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} minTickGap={14} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} tickFormatter={(n) => (n >= 1000 ? `${Math.round(n / 1000)}к` : n)} />
              <Tooltip formatter={(v) => `${fmt(Number(v))} посадок`} contentStyle={{ borderRadius: 10, fontSize: 12 }} />
              <Legend formatter={(n) => (n === 'base' ? 'Прогноз модели' : 'С коэффициентами')} wrapperStyle={{ fontSize: 11 }} />
              {(presets?.calendar.days ?? []).filter((d) => Number(d.slice(5, 7)) === month).map((d) => <ReferenceLine key={d} x={`${d.slice(8)}.${d.slice(5, 7)}`} stroke="#f0a339" strokeDasharray="3 3" label={{ value: 'праздник', fontSize: 9, fill: '#c98218', position: 'insideTopLeft' }} />)}
              <Line type="monotone" dataKey="base" stroke="#a9b6d3" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="adjusted" stroke="#4f75f3" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        {presets && <div className="x-note">{presets.disclaimer} Источники: <a href={presets.sources.calendar} target="_blank" rel="noreferrer">производственный календарь РФ</a>, <a href={presets.sources.weather} target="_blank" rel="noreferrer">архив погоды Open-Meteo</a>.</div>}
      </article>
    </section>
  )
}
