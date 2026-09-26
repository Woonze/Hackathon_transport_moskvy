import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { fmt, getJson, lastDay, pad, useDebounced, useLive } from './shared'
import type { RouteId } from './shared'
import './panels.css'

type Stop = { route: number; direction: number; sequence: number; stop_id: string; name: string; lat: number; lon: number; district: string | null; is_hub: boolean }
type FlowStop = Stop & { boardings: number; share: number }
type Segment = { direction: number; sequence: number; from: Stop; to: Stop; passengers: number }
type Flow = { route_total: number; method: string; stops: FlowStop[] }
type Segments = { segments: Segment[]; peak: Segment | null }
type Series = { name: string; data: { date?: string; hour?: number; passengers: number }[] }
type RouteSummary = { id: number; historical_total: number; forecast_total: number }

const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t)
// от синего (мало) к красному (много)
const loadColor = (t: number) => `rgb(${lerp(77, 230, t)},${lerp(116, 95, t)},${lerp(239, 115, t)})`

function Fit({ points, sig }: { points: [number, number][]; sig: string }) {
  const map = useMap()
  useEffect(() => { if (points.length) map.fitBounds(points, { padding: [28, 28] }) }, [sig]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function StopsMap({ route: dashboardRoute, routeSummaries }: { route: RouteId; routeSummaries: RouteSummary[] }) {
  const [routes, setRoutes] = useState<number[]>([])
  const [route, setRoute] = useState(7)
  const [direction, setDirection] = useState(0)
  const [date, setDate] = useState('2025-11-03')
  const [hours, setHours] = useState<[number, number]>([0, 23])
  const [flow, setFlow] = useState<Flow | null>(null)
  const [segs, setSegs] = useState<Segments | null>(null)
  const [selected, setSelected] = useState<FlowStop | null>(null)
  const [mode, setMode] = useState<'hour' | 'day'>('hour')
  const [series, setSeries] = useState<Series | null>(null)
  const [error, setError] = useState('')
  const [liveOn, setLiveOn] = useState(false)
  const live = useLive(liveOn)
  // в реальном времени карта показывает историю за последний день, в котором есть данные, и обновляется по событиям потока
  const kind = liveOn ? 'history' : 'forecast'
  const day = liveOn ? (live.last?.history_end ?? '2025-10-31') : date
  const version = liveOn ? (live.last?.version ?? '') : ''
  const selKey = `${route}|${kind}|${day}|${hours[0]}|${hours[1]}`
  const debounced = useDebounced(useMemo(() => `${selKey}|${version}`, [selKey, version]), liveOn ? 0 : 250)

  useEffect(() => {
    const controller = new AbortController()
    getJson<{ routes: number[] }>('/api/v1/stops', controller.signal)
      .then((r) => { setRoutes(r.routes); setRoute((cur) => (r.routes.includes(cur) ? cur : r.routes[0])) })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [])
  useEffect(() => { if (dashboardRoute !== 'all' && routes.includes(dashboardRoute)) setRoute(dashboardRoute) }, [dashboardRoute, routes])

  useEffect(() => {
    if (liveOn && !live.last) return // ждём первое событие потока: из него известен последний день с данными
    const controller = new AbortController()
    const [r, k, d, hf, ht] = debounced.split('|')
    const q = `route=${r}&kind=${k}&start=${d}&end=${d}&hour_from=${hf}&hour_to=${ht}`
    setError('')
    Promise.all([getJson<Flow>(`/api/v1/stops/flow?${q}`, controller.signal), getJson<Segments>(`/api/v1/stops/segments?${q}`, controller.signal)])
      .then(([f, s]) => {
        setFlow(f); setSegs(s)
        setSelected((cur) => (cur ? (f.stops.find((x) => x.stop_id === cur.stop_id && x.direction === cur.direction) ?? null) : cur)) // выбор остановки переживает обновление
      })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [debounced]) // eslint-disable-line react-hooks/exhaustive-deps
  // смена маршрута, режима, даты или часов сбрасывает выбор и старые данные; обновление по потоку и смена последнего дня в реальном времени их сохраняют
  const resetKey = `${route}|${kind}|${liveOn ? 'live' : day}|${hours[0]}|${hours[1]}`
  useEffect(() => { setSelected(null); setFlow(null); setSegs(null) }, [resetKey])

  useEffect(() => {
    if (!selected) { setSeries(null); return }
    const controller = new AbortController()
    const [y, m] = day.split('-').map(Number)
    const range = mode === 'hour' ? `start=${day}&end=${day}&granularity=hour` : `start=${y}-${pad(m)}-01&end=${y}-${pad(m)}-${pad(lastDay(y, m))}&granularity=day`
    if (!liveOn) setSeries(null)
    getJson<Series>(`/api/v1/stops/${selected.stop_id}/series?kind=${kind}&${range}&route=${route}`, controller.signal)
      .then(setSeries)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [selected?.stop_id, day, mode, kind, version, route]) // eslint-disable-line react-hooks/exhaustive-deps

  const stops = useMemo(() => (flow?.stops ?? []).filter((s) => s.direction === direction), [flow, direction])
  const segments = useMemo(() => (segs?.segments ?? []).filter((s) => s.direction === direction), [segs, direction])
  const maxLoad = Math.max(1, ...segments.map((s) => s.passengers))
  const maxBoard = Math.max(1, ...stops.map((s) => s.boardings))
  const points = useMemo(() => stops.map((s) => [s.lat, s.lon] as [number, number]), [stops])
  const top = useMemo(() => [...stops].sort((a, b) => b.boardings - a.boardings).slice(0, 6), [stops])
  const directions = useMemo(() => [...new Set((flow?.stops ?? []).map((s) => s.direction))].sort(), [flow])
  const selectedRouteHasNoHistory = routeSummaries.find((item) => item.id === route)?.historical_total === 0
  const chart = (series?.data ?? []).map((p) => ({ label: p.hour !== undefined ? `${pad(p.hour)}:00` : (p.date ?? '').slice(8), passengers: p.passengers }))
  const peak = useMemo(() => segments.reduce<Segment | null>((best, s) => (!best || s.passengers > best.passengers ? s : best), null), [segments])

  return (
    <section className="x-section">
      <article className="panel x-panel">
        <div className="panel-heading">
          <div><div className="panel-title">Остановки и участки на карте</div><div className="panel-subtitle">Оценка посадок по остановкам и загрузки участков · выберите остановку, чтобы увидеть динамику во времени</div></div>
          <div className="segmented">{(directions.length ? directions : [0, 1]).map((d) => <button key={d} className={direction === d ? 'active' : ''} onClick={() => { setDirection(d); setSelected(null) }}>Направление {d}</button>)}</div>
        </div>
        <div className="x-controls">
          <label className="x-field">Маршрут<select value={route} onChange={(e) => setRoute(Number(e.target.value))}>{routes.map((r) => <option key={r} value={r}>Трамвай {r}</option>)}</select></label>
          <div className="x-field">Режим<div className="segmented"><button className={!liveOn ? 'active' : ''} onClick={() => setLiveOn(false)}>Прогноз</button><button className={liveOn ? 'active' : ''} onClick={() => setLiveOn(true)}>В реальном времени</button></div></div>
          <label className="x-field">Дата<input type="date" min="2025-11-01" max="2025-12-31" value={liveOn ? day : date} disabled={liveOn} title={liveOn ? 'В реальном времени показывается последний день с данными' : undefined} onChange={(e) => e.target.value && setDate(e.target.value)} /></label>
          <label className="x-field">Час с<select value={hours[0]} onChange={(e) => setHours([Number(e.target.value), Math.max(Number(e.target.value), hours[1])])}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}:00</option>)}</select></label>
          <label className="x-field">Час по<select value={hours[1]} onChange={(e) => setHours([Math.min(hours[0], Number(e.target.value)), Number(e.target.value)])}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}:59</option>)}</select></label>
          {flow && <div className="x-kpis" style={{ margin: 0 }}><div><b>{fmt(flow.route_total)}</b><span>посадок на маршруте за выбранное время</span></div></div>}
        </div>
        {selectedRouteHasNoHistory && <div className="info-banner" role="status">Для маршрута {route} в истории нет наблюдений. Нулевые значения остановочной оценки не означают подтверждённое отсутствие пассажиров.</div>}
        {liveOn && (
          <div className={`x-live x-live-${live.status}`} role="status">
            <span className="x-live-dot" />
            {live.status === 'online' && live.last ? <>Онлайн · данные по {live.last.history_end.split('-').reverse().join('.')} · принято посадок: {fmt(live.last.ingested_boardings)} · обновлений: {live.events}{live.receivedAt ? ` · ${live.receivedAt.toLocaleTimeString('ru-RU')}` : ''}</>
              : live.status === 'offline' ? 'Нет связи с потоком, переподключаюсь…' : 'Подключаюсь к потоку…'}
          </div>
        )}
        {error && <div className="x-error">{error}</div>}
        <div className="x-split">
          <div>
            <div className="x-map">
              <MapContainer center={[55.7558, 37.6173]} zoom={11} scrollWheelZoom className="leaflet-map" style={{ height: '100%' }}>
                <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <Fit points={points} sig={`${route}-${direction}-${points.length}`} />
                {segments.map((s) => (
                  <Polyline key={`${s.direction}-${s.sequence}`} positions={[[s.from.lat, s.from.lon], [s.to.lat, s.to.lon]]} pathOptions={{ color: loadColor(s.passengers / maxLoad), weight: 9, opacity: 0.95, lineCap: 'round' }}>
                    <Tooltip sticky>{s.from.name} → {s.to.name}: ~{fmt(s.passengers)} пасс.</Tooltip>
                  </Polyline>
                ))}
                {stops.map((s) => (
                  <CircleMarker key={`${s.direction}-${s.sequence}`} center={[s.lat, s.lon]} radius={1.8 + 3.2 * Math.sqrt(s.boardings / maxBoard)}
                    pathOptions={{ color: selected?.stop_id === s.stop_id ? '#e65f73' : '#29354a', weight: selected?.stop_id === s.stop_id ? 3 : 1.2, fillColor: '#fff', fillOpacity: 1 }}
                    eventHandlers={{ click: () => setSelected(s) }}>
                    <Tooltip>{s.name}{s.is_hub ? ' ⇄' : ''} · ~{fmt(s.boardings)} посадок</Tooltip>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>
            <div className="x-legend"><span>Загрузка участка:</span><span>мало</span><span className="x-gradient" /><span>много (до ~{fmt(maxLoad)})</span><span>· размер точки — посадки на остановке</span></div>
          </div>
          <div>
            {selected ? (
              <>
                <div className="x-stop-title">{selected.name}{selected.is_hub ? ' ⇄' : ''}</div>
                <div className="panel-subtitle" style={{ marginBottom: 8 }}>{selected.district ?? 'район не указан'} · ~{fmt(selected.boardings)} посадок · {(selected.share * 100).toFixed(1)}% потока маршрута</div>
                <div className="segmented" style={{ width: 'fit-content', marginBottom: 6 }}><button className={mode === 'hour' ? 'active' : ''} onClick={() => setMode('hour')}>По часам</button><button className={mode === 'day' ? 'active' : ''} onClick={() => setMode('day')}>По дням месяца</button></div>
                <div className="x-chart" style={{ height: 230 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chart} margin={{ top: 8, right: 6, left: -18, bottom: 0 }}>
                      <defs><linearGradient id="stopGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#537dff" stopOpacity={0.25} /><stop offset="100%" stopColor="#537dff" stopOpacity={0.02} /></linearGradient></defs>
                      <CartesianGrid stroke="#1b2b3b" vertical={false} />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} minTickGap={16} />
                      <YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 10 }} />
                      <ChartTooltip formatter={(v) => [`~${fmt(Number(v))} посадок`, 'Оценка']} contentStyle={{ border: '1px solid #26394d', background: '#0b1722', color: '#dce6f5', borderRadius: 8, fontSize: 11 }} />
                      <Area type="monotone" dataKey="passengers" stroke="#4f75f3" strokeWidth={2.4} fill="url(#stopGradient)" isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <>
                <div className="x-stop-title">Остановки с наибольшими посадками</div>
                <div className="panel-subtitle" style={{ marginBottom: 8 }}>Кликните по точке на карте или выберите из списка</div>
                {top.map((s) => <button key={s.stop_id + s.sequence} className="x-chip" style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 6, borderRadius: 8 }} onClick={() => setSelected(s)}>{s.sequence}. {s.name} — ~{fmt(s.boardings)}</button>)}
                {!top.length && <div className="x-empty">Нет данных</div>}
              </>
            )}
            {peak && <div className="x-note">Самый загруженный участок направления {peak.direction}: «{peak.from.name}» → «{peak.to.name}», ~{fmt(peak.passengers)} пассажиров.</div>}
          </div>
        </div>
        <div className="x-note">Остановочные значения — <b>оценка по эвристике</b>: в данных валидаций нет привязки к остановкам, поэтому посадки маршрута распределяются по остановкам справочника по весам (начальная, конечная и узловая остановки), а загрузка участков считается моделью длины поездки. Остановки есть только у маршрутов 1, 5, 7, 11 и 12.</div>
      </article>
    </section>
  )
}
