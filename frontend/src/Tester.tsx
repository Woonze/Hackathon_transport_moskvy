import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useLive } from './panels/shared'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type Row = Record<string, string | number>
type Result = { url: string; method: string; status: number; ms: number; serverMs: string | null; data: unknown }
type RouteInfo = { id: number; name: string; historical_total: number; forecast_total: number }

const API = import.meta.env.VITE_API_URL ?? ''
const COLORS = ['#2e6bff', '#e65f73', '#00a78b', '#f0a339', '#8556e8', '#14a5c7', '#62748b', '#b15cb7', '#46804c', '#dc8b23']
const fmt = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))

async function call(url: string, init?: RequestInit): Promise<Result> {
  const started = performance.now()
  try {
    const r = await fetch(API + url, init)
    const text = await r.text()
    let data: unknown = text
    try { data = JSON.parse(text) } catch { /* не JSON — оставляем текстом */ }
    return { url, method: init?.method ?? 'GET', status: r.status, ms: performance.now() - started, serverMs: r.headers.get('x-process-time-ms'), data }
  } catch (e) {
    return { url, method: init?.method ?? 'GET', status: 0, ms: performance.now() - started, serverMs: null, data: `Сервер недоступен: ${String(e)}` }
  }
}

const post = (url: string, body: unknown, extra: Record<string, string> = {}) =>
  call(url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...extra }, body: JSON.stringify(body) })

function pivot(rows: Row[], xOf: (r: Row) => string, sOf: (r: Row) => string, value = 'passengers') {
  const x = new Map<string, Row>()
  const keys = new Set<string>()
  for (const r of rows) {
    const k = xOf(r), s = sOf(r)
    keys.add(s)
    const cell = x.get(k) ?? { x: k }
    cell[s] = ((cell[s] as number) ?? 0) + (r[value] as number)
    x.set(k, cell)
  }
  return { data: [...x.values()].sort((a, b) => String(a.x).localeCompare(String(b.x))), keys: [...keys] }
}

const xLabel = (r: Row) => (r.month as string) ?? (r.hour !== undefined ? `${String(r.date).slice(5)} ${String(r.hour).padStart(2, '0')}ч` : (r.date as string))

function Chart({ data, keys, height = 260 }: { data: Row[]; keys: string[]; height?: number }) {
  if (!data.length) return <p className="t-muted">Нет точек для графика</p>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="#edf0f5" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 11 }} minTickGap={24} />
        <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt} width={64} />
        <Tooltip formatter={(v) => fmt(Number(v))} />
        {keys.length > 1 && <Legend />}
        {keys.map((k, i) => <Line key={k} dataKey={k} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={2} isAnimationActive={false} />)}
      </LineChart>
    </ResponsiveContainer>
  )
}

function Panel({ res }: { res: Result | null }) {
  if (!res) return null
  const ok = res.status >= 200 && res.status < 300
  const raw = typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2)
  return (
    <div className="t-panel">
      <div className="t-line">
        <span className={`t-badge ${ok ? 'ok' : 'bad'}`}>{res.status || 'ERR'}</span>
        <code>{res.method} {res.url}</code>
      </div>
      <div className="t-muted">{res.ms.toFixed(0)} мс на клиенте{res.serverMs ? `, ${res.serverMs} мс обработка на сервере` : ''}</div>
      {!ok && typeof res.data === 'object' && res.data !== null && 'detail' in res.data && (
        <div className="t-error">{(res.data as { detail: string; code?: string }).detail} <code>{(res.data as { code?: string }).code}</code></div>
      )}
      <details><summary>Сырой ответ</summary><pre>{raw.length > 20000 ? `${raw.slice(0, 20000)}\n… обрезано (${raw.length} символов)` : raw}</pre></details>
    </div>
  )
}

function Table({ rows, limit = 100 }: { rows: Row[]; limit?: number }) {
  if (!rows.length) return null
  const cols = Object.keys(rows[0])
  return (
    <div className="t-scroll">
      <table>
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{rows.slice(0, limit).map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{typeof r[c] === 'number' ? fmt(r[c] as number) : String(r[c] ?? '')}</td>)}</tr>)}</tbody>
      </table>
      {rows.length > limit && <p className="t-muted">Показаны первые {limit} из {fmt(rows.length)} строк</p>}
    </div>
  )
}

const Field = ({ label, children }: { label: string; children: ReactNode }) => <label className="t-field"><span>{label}</span>{children}</label>

function RouteSelect({ routes, value, onChange, all = true }: { routes: number[]; value: string; onChange: (v: string) => void; all?: boolean }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {all && <option value="">все маршруты</option>}
      {routes.map((r) => <option key={r} value={r}>Маршрут {r}</option>)}
    </select>
  )
}

const GRAN = ['day', 'hour', 'month']
const rangeFor = (kind: string) => (kind === 'forecast' ? ['2025-11-01', '2025-11-30'] : ['2025-09-01', '2025-09-30'])

function SeriesTab({ routes }: { routes: number[] }) {
  const [kind, setKind] = useState('forecast')
  const [route, setRoute] = useState('')
  const [[start, end], setRange] = useState(rangeFor('forecast'))
  const [gran, setGran] = useState('day')
  const [corr, setCorr] = useState('')
  const [res, setRes] = useState<Result | null>(null)
  const run = async () => {
    const q = new URLSearchParams({ start, end, granularity: gran })
    if (route) q.set('route', route)
    if (corr && kind === 'forecast') q.set('corrections', corr)
    setRes(await call(`/api/v1/${kind}?${q}`))
  }
  const rows = res && Array.isArray(res.data) ? (res.data as Row[]) : []
  const { data, keys } = pivot(rows, xLabel, (r) => `Маршрут ${r.route}`)
  return (
    <>
      <div className="t-form">
        <Field label="Что"><select value={kind} onChange={(e) => { setKind(e.target.value); setRange(rangeFor(e.target.value)) }}><option value="forecast">Прогноз</option><option value="history">История</option></select></Field>
        <Field label="Маршрут"><RouteSelect routes={routes} value={route} onChange={setRoute} /></Field>
        <Field label="С"><input type="date" value={start} onChange={(e) => setRange([e.target.value, end])} /></Field>
        <Field label="По"><input type="date" value={end} onChange={(e) => setRange([start, e.target.value])} /></Field>
        <Field label="Детализация"><select value={gran} onChange={(e) => setGran(e.target.value)}>{GRAN.map((g) => <option key={g}>{g}</option>)}</select></Field>
        <Field label="Поправки (прогноз)"><input value={corr} onChange={(e) => setCorr(e.target.value)} placeholder="calendar,regime,weather" /></Field>
        <button onClick={run}>Запросить</button>
      </div>
      <Panel res={res} />
      {rows.length > 0 && <><Chart data={data} keys={keys} /><Table rows={rows} /></>}
    </>
  )
}

function ExportTab({ routes }: { routes: number[] }) {
  const [kind, setKind] = useState('forecast')
  const [format, setFormat] = useState('csv')
  const [route, setRoute] = useState('')
  const [[start, end], setRange] = useState(rangeFor('forecast'))
  const [gran, setGran] = useState('day')
  const [info, setInfo] = useState<Row | null>(null)
  const [corr, setCorr] = useState('')
  const run = async () => {
    const q = new URLSearchParams({ kind, format, granularity: gran, start, end })
    if (route) q.set('route', route)
    if (corr && kind === 'forecast') q.set('corrections', corr)
    const r = await fetch(`${API}/api/v1/export?${q}`)
    const blob = await r.blob()
    const disposition = r.headers.get('content-disposition') ?? ''
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'export'
    setInfo({ статус: r.status, тип: r.headers.get('content-type') ?? '', размер: `${(blob.size / 1024).toFixed(1)} КБ`, файл: name, ...(r.ok ? {} : { ошибка: await blob.text() }) })
    if (r.ok) {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob); a.download = name; a.click(); URL.revokeObjectURL(a.href)
    }
  }
  return (
    <>
      <div className="t-form">
        <Field label="Что"><select value={kind} onChange={(e) => { setKind(e.target.value); setRange(rangeFor(e.target.value)) }}><option value="forecast">Прогноз</option><option value="history">История</option></select></Field>
        <Field label="Формат"><select value={format} onChange={(e) => setFormat(e.target.value)}><option>csv</option><option>xlsx</option></select></Field>
        <Field label="Маршрут"><RouteSelect routes={routes} value={route} onChange={setRoute} /></Field>
        <Field label="С"><input type="date" value={start} onChange={(e) => setRange([e.target.value, end])} /></Field>
        <Field label="По"><input type="date" value={end} onChange={(e) => setRange([start, e.target.value])} /></Field>
        <Field label="Детализация"><select value={gran} onChange={(e) => setGran(e.target.value)}>{GRAN.map((g) => <option key={g}>{g}</option>)}</select></Field>
        <Field label="Поправки (прогноз)"><input value={corr} onChange={(e) => setCorr(e.target.value)} placeholder="calendar,regime,weather" /></Field>
        <button onClick={run}>Скачать</button>
      </div>
      {info && <div className="t-panel"><Table rows={[info]} /></div>}
    </>
  )
}

function AdjustTab({ routes }: { routes: number[] }) {
  const [route, setRoute] = useState('7')
  const [[start, end], setRange] = useState(['2025-12-15', '2025-12-31'])
  const [f, setF] = useState({ weather: 1, event: 1, season: 1 })
  const [calendar, setCalendar] = useState(false)
  const [regime, setRegime] = useState(false)
  const [weatherAuto, setWeatherAuto] = useState(false)
  const [rule, setRule] = useState({ on: true, start: '2025-12-25', end: '2025-12-31', hour_from: 0, hour_to: 23, factor: 0.8, routes: '' })
  const [res, setRes] = useState<Result | null>(null)
  const run = async () => {
    const body: Record<string, unknown> = { start, end, granularity: 'day', factors: f, rules: [], calendar, regime, weather_auto: weatherAuto }
    if (route) body.route = Number(route)
    if (rule.on) {
      body.rules = [{ start: rule.start, end: rule.end, factor: rule.factor, hour_from: rule.hour_from, hour_to: rule.hour_to,
        ...(rule.routes.trim() ? { routes: rule.routes.split(',').map((x) => Number(x.trim())) } : {}), label: 'проверка' }]
    }
    setRes(await post('/api/v1/forecast/adjusted', body))
  }
  const body = res && res.status === 200 ? (res.data as { summary: Record<string, number>; data: Row[] }) : null
  const chart = body ? pivot(body.data.flatMap((r) => [{ ...r, s: 'Прогноз модели', passengers: r.base }, { ...r, s: 'С коэффициентами' }]), xLabel, (r) => r.s as string) : null
  const slider = (k: keyof typeof f, label: string) => (
    <Field label={`${label}: ×${f[k].toFixed(2)}`}><input type="range" min={0.5} max={1.5} step={0.05} value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} /></Field>
  )
  return (
    <>
      <div className="t-form">
        <Field label="Маршрут"><RouteSelect routes={routes} value={route} onChange={setRoute} /></Field>
        <Field label="С"><input type="date" value={start} onChange={(e) => setRange([e.target.value, end])} /></Field>
        <Field label="По"><input type="date" value={end} onChange={(e) => setRange([start, e.target.value])} /></Field>
        {slider('weather', 'Погода')}{slider('event', 'Событие')}{slider('season', 'Сезон')}
        <label className="t-check"><input type="checkbox" checked={calendar} onChange={(e) => setCalendar(e.target.checked)} /> Календарь РФ (уже учтён ML-моделью; флаг совместимости)</label>
        <label className="t-check"><input type="checkbox" checked={regime} onChange={(e) => setRegime(e.target.checked)} /> Сдвиги режима</label>
        <label className="t-check"><input type="checkbox" checked={weatherAuto} onChange={(e) => setWeatherAuto(e.target.checked)} /> Погода по архиву</label>
      </div>
      <div className="t-form">
        <label className="t-check"><input type="checkbox" checked={rule.on} onChange={(e) => setRule({ ...rule, on: e.target.checked })} /> Точечное правило</label>
        <Field label="С"><input type="date" value={rule.start} onChange={(e) => setRule({ ...rule, start: e.target.value })} /></Field>
        <Field label="По"><input type="date" value={rule.end} onChange={(e) => setRule({ ...rule, end: e.target.value })} /></Field>
        <Field label="Час с"><input type="number" min={0} max={23} value={rule.hour_from} onChange={(e) => setRule({ ...rule, hour_from: Number(e.target.value) })} /></Field>
        <Field label="Час по"><input type="number" min={0} max={23} value={rule.hour_to} onChange={(e) => setRule({ ...rule, hour_to: Number(e.target.value) })} /></Field>
        <Field label="Множитель"><input type="number" step={0.05} value={rule.factor} onChange={(e) => setRule({ ...rule, factor: Number(e.target.value) })} /></Field>
        <Field label="Маршруты правила (через запятую)"><input value={rule.routes} onChange={(e) => setRule({ ...rule, routes: e.target.value })} placeholder="все" /></Field>
        <button onClick={run}>Пересчитать</button>
      </div>
      <Panel res={res} />
      {body && chart && (
        <>
          <div className="t-cards">
            <div><b>{fmt(body.summary.base_total)}</b><span>прогноз модели</span></div>
            <div><b>{fmt(body.summary.adjusted_total)}</b><span>с коэффициентами</span></div>
            <div><b>{body.summary.delta_pct === null ? '—' : `${body.summary.delta_pct > 0 ? '+' : ''}${body.summary.delta_pct}%`}</b><span>изменение ({fmt(body.summary.delta)})</span></div>
            <div><b>×{body.summary.global_multiplier}</b><span>общий множитель</span></div>
          </div>
          <Chart data={chart.data} keys={chart.keys} />
        </>
      )}
    </>
  )
}

function YearTab({ routes }: { routes: number[] }) {
  const [route, setRoute] = useState('')
  const [growth, setGrowth] = useState(1)
  const [res, setRes] = useState<Result | null>(null)
  const run = async () => setRes(await call(`/api/v1/forecast/year?growth=${growth}${route ? `&route=${route}` : ''}`))
  const body = res && res.status === 200 ? (res.data as { note: string; data: Row[] }) : null
  const label: Record<string, string> = { fact: 'Факт', forecast: 'Прогноз модели', scenario: 'Сценарий 2026' }
  const chart = body ? pivot(body.data, (r) => r.month as string, (r) => label[r.source as string]) : null
  return (
    <>
      <div className="t-form">
        <Field label="Маршрут"><RouteSelect routes={routes} value={route} onChange={setRoute} /></Field>
        <Field label={`Рост для 2026: ×${growth.toFixed(2)}`}><input type="range" min={0.5} max={1.5} step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} /></Field>
        <button onClick={run}>Показать</button>
      </div>
      <Panel res={res} />
      {body && chart && <><p className="t-note">{body.note}</p><Chart data={chart.data} keys={chart.keys} /></>}
    </>
  )
}

function DispatchTab({ routes }: { routes: number[] }) {
  const [route, setRoute] = useState('7')
  const [date, setDate] = useState('2025-11-10')
  const [corr, setCorr] = useState('calendar,regime')
  const [capacity, setCapacity] = useState('')
  const [vehicles, setVehicles] = useState('')
  const [res, setRes] = useState<Result | null>(null)
  const q = () => `route=${route}&corrections=${corr}${capacity && vehicles ? `&capacity=${capacity}&vehicles=${vehicles}` : ''}`
  const rows = res && res.status === 200 && (res.data as { hours?: Row[] }).hours
  return (
    <>
      <div className="t-form">
        <Field label="Маршрут"><RouteSelect routes={routes} value={route} onChange={setRoute} /></Field>
        <Field label="Дата"><input type="date" min="2025-11-01" max="2025-12-31" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Поправки"><input value={corr} onChange={(e) => setCorr(e.target.value)} placeholder="calendar,regime,weather" /></Field>
        <Field label="Посадок за час на вагон"><input type="number" value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="необязательно" /></Field>
        <Field label="Вагонов на линии"><input type="number" value={vehicles} onChange={(e) => setVehicles(e.target.value)} placeholder="необязательно" /></Field>
        <button onClick={async () => setRes(await call(`/api/v1/dispatch/day?date=${date}&${q()}`))}>Сводка на день</button>
        <button className="ghost" onClick={async () => setRes(await call(`/api/v1/dispatch/savings?corrections=${corr}${route ? `&route=${route}` : ''}&limit=20`))}>Дни для пересмотра выпуска</button>
      </div>
      <Panel res={res} />
      {rows && <Chart data={(rows as Row[]).map((r) => ({ x: `${r.hour}ч`, Посадки: r.boardings, 'Обычный день': r.typical }))} keys={['Посадки', 'Обычный день']} height={220} />}
    </>
  )
}

type Flow = { route_total: number; stops: Row[] }
type Seg = { segments: { direction: number; sequence: number; passengers: number; from: { name: string }; to: { name: string } }[]; peak: { direction: number; from: { name: string }; to: { name: string }; passengers: number } | null }

function StopsTab() {
  const [avail, setAvail] = useState<number[]>([])
  const [route, setRoute] = useState('7')
  const [kind, setKind] = useState('forecast')
  const [[start, end], setRange] = useState(['2025-11-03', '2025-11-09'])
  const [hours, setHours] = useState<[number, number]>([0, 23])
  const [flow, setFlow] = useState<Result | null>(null)
  const [seg, setSeg] = useState<Result | null>(null)
  const [ser, setSer] = useState<Result | null>(null)
  useEffect(() => { call('/api/v1/stops').then((r) => { if (r.status === 200) setAvail((r.data as { routes: number[] }).routes) }) }, [])
  const run = async () => {
    const q = new URLSearchParams({ route, kind, start, end, hour_from: String(hours[0]), hour_to: String(hours[1]) })
    setSer(null)
    setFlow(await call(`/api/v1/stops/flow?${q}`)); setSeg(await call(`/api/v1/stops/segments?${q}`))
  }
  const openSeries = async (id: string) => setSer(await call(`/api/v1/stops/${id}/series?kind=${kind}&start=${start}&end=${end}&granularity=day`))
  const f = flow && flow.status === 200 ? (flow.data as Flow) : null
  const s = seg && seg.status === 200 ? (seg.data as Seg) : null
  const segChart = s ? pivot(s.segments.map((x) => ({ ...x, n: String(x.sequence).padStart(2, '0'), d: `Направление ${x.direction}` })) as unknown as Row[], (r) => r.n as string, (r) => r.d as string) : null
  const serRows = ser && ser.status === 200 ? ((ser.data as { data: Row[]; name: string }).data) : []
  const top = f ? [...f.stops].sort((a, b) => (b.boardings as number) - (a.boardings as number)).slice(0, 15) : []
  return (
    <>
      <p className="t-note">Остановочные значения — оценка по эвристике (в валидациях нет остановок). Есть только у маршрутов справочника.</p>
      <div className="t-form">
        <Field label="Маршрут"><RouteSelect routes={avail.length ? avail : [1, 5, 7, 11, 12]} value={route} onChange={setRoute} all={false} /></Field>
        <Field label="Что"><select value={kind} onChange={(e) => { setKind(e.target.value); setRange(e.target.value === 'forecast' ? ['2025-11-03', '2025-11-09'] : ['2025-10-20', '2025-10-26']) }}><option value="forecast">Прогноз</option><option value="history">История</option></select></Field>
        <Field label="С"><input type="date" value={start} onChange={(e) => setRange([e.target.value, end])} /></Field>
        <Field label="По"><input type="date" value={end} onChange={(e) => setRange([start, e.target.value])} /></Field>
        <Field label="Час с"><input type="number" min={0} max={23} value={hours[0]} onChange={(e) => setHours([Number(e.target.value), hours[1]])} /></Field>
        <Field label="Час по"><input type="number" min={0} max={23} value={hours[1]} onChange={(e) => setHours([hours[0], Number(e.target.value)])} /></Field>
        <button onClick={run}>Рассчитать</button>
      </div>
      <Panel res={flow} /><Panel res={seg} />
      {s && segChart && (
        <>
          <h3>Загрузка участков (номер участка по порядку)</h3>
          {s.peak && <p className="t-note">Пик: направление {s.peak.direction}, «{s.peak.from.name}» → «{s.peak.to.name}», {fmt(s.peak.passengers)} пассажиров</p>}
          <Chart data={segChart.data} keys={segChart.keys} />
        </>
      )}
      {f && (
        <>
          <h3>Остановки с наибольшими посадками (всего по маршруту {fmt(f.route_total)}) — клик по строке открывает динамику</h3>
          <div className="t-scroll"><table>
            <thead><tr><th>направление</th><th>№</th><th>остановка</th><th>район</th><th>посадки</th><th>доля</th></tr></thead>
            <tbody>{top.map((r) => <tr key={`${r.direction}-${r.sequence}`} className="t-click" onClick={() => openSeries(r.stop_id as string)}>
              <td>{r.direction}</td><td>{r.sequence}</td><td>{r.name}{r.is_hub ? ' ⇄' : ''}</td><td>{r.district}</td><td>{fmt(r.boardings as number)}</td><td>{((r.share as number) * 100).toFixed(1)}%</td></tr>)}</tbody>
          </table></div>
        </>
      )}
      <Panel res={ser} />
      {serRows.length > 0 && <Chart data={pivot(serRows, xLabel, () => (ser!.data as { name: string }).name).data} keys={[(ser!.data as { name: string }).name]} height={200} />}
    </>
  )
}

const SAMPLE = [
  { tran_no: 1, device_no: 5, tran_date_time: '2025-11-03 08:15:00', validation_result: 1, ngpt_route: '7 трамвай' },
  { tran_no: 2, device_no: 5, tran_date_time: '2025-11-03 08:40:12', validation_result: 1, ngpt_route: '7 трамвай' },
  { tran_no: 2, device_no: 5, tran_date_time: '2025-11-03 08:40:13', validation_result: 1, ngpt_route: '7 трамвай' },
  { tran_no: 3, device_no: 6, tran_date_time: '2025-11-03 09:05:00', validation_result: 90, ngpt_route: '7 трамвай' },
  { tran_no: 4, device_no: 6, tran_date_time: '2025-11-03 09:10:00', validation_result: 1, ngpt_route: '99 трамвай' },
  { tran_no: 5, device_no: 6, tran_date_time: 'вчера', validation_result: 1, ngpt_route: '7 трамвай' },
]

function IngestTab({ apiKey }: { apiKey: string }) {
  const [text, setText] = useState(JSON.stringify(SAMPLE, null, 2))
  const [batch, setBatch] = useState('')
  const [complete, setComplete] = useState(false)
  const [res, setRes] = useState<Result | null>(null)
  const [check, setCheck] = useState<Result | null>(null)
  const [listen, setListen] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const live = useLive(listen, (e) => setLog((l) => [`${new Date().toLocaleTimeString('ru-RU')} update · данные по ${e.history_end} · принято посадок ${e.ingested_boardings} · воркер ${e.worker_pid}`, ...l].slice(0, 8)))
  const send = async () => {
    let records: unknown
    try { records = JSON.parse(text) } catch (e) { setRes({ url: '/api/v1/ingest/validations', method: 'POST', status: 0, ms: 0, serverMs: null, data: `Некорректный JSON: ${String(e)}` }); return }
    setRes(await post('/api/v1/ingest/validations', { records, complete, ...(batch ? { batch_id: batch } : {}) }, apiKey ? { 'X-API-Key': apiKey } : {}))
  }
  return (
    <>
      <p className="t-note">Пакет сразу попадает в историю и сохраняется в <code>artifacts/ingested.csv</code>. ML-модель обучается на новых датах, когда отправитель подтвердил полноту их данных. Повторная отправка пакета не задваивает посадки.</p>
      <textarea className="t-area" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <div className="t-form">
        <Field label="batch_id (необязательно)"><input value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="по содержимому" /></Field>
        <label className="t-check"><input type="checkbox" checked={complete} onChange={(e) => setComplete(e.target.checked)} /> Данные за даты пакета полные: завершить дни и переобучить ML</label>
        <button onClick={send}>Отправить пакет</button>
        <button className="ghost" onClick={async () => setCheck(await call('/api/v1/history?route=7&granularity=hour&start=2025-11-03&end=2025-11-03'))}>Проверить историю 03.11, маршрут 7</button>
      </div>
      <Panel res={res} /><Panel res={check} />
      <div className="t-form" style={{ marginTop: 14 }}>
        <button className="ghost" onClick={() => { setListen((v) => !v); setLog([]) }}>{listen ? 'Отключить поток /stream' : 'Подключить поток /stream (SSE)'}</button>
        <span className="t-note" style={{ margin: 0 }}>Статус: {live.status === 'online' ? 'онлайн' : live.status === 'connecting' ? 'подключение' : live.status === 'offline' ? 'нет связи' : 'выключен'}. После отправки пакета здесь появится событие update.</span>
      </div>
      {log.length > 0 && <div className="t-panel"><pre data-testid="live-log">{log.join('\n')}</pre></div>}
      {check && Array.isArray(check.data) && <Chart data={(check.data as Row[]).map((r) => ({ x: `${r.hour}ч`, Посадки: r.passengers }))} keys={['Посадки']} height={200} />}
    </>
  )
}

const CASES: { name: string; url: string; body?: unknown; status: number; code: string; noKey?: boolean; onlyGuarded?: boolean }[] = [
  { name: 'Дата начала позже конца', url: '/api/v1/forecast?start=2025-12-01&end=2025-11-01', status: 400, code: 'bad_range' },
  { name: 'Неизвестный маршрут', url: '/api/v1/forecast?route=99', status: 404, code: 'route_not_found' },
  { name: 'Период вне данных', url: '/api/v1/forecast?start=2024-01-01&end=2024-01-05', status: 422, code: 'out_of_range' },
  { name: 'Слишком широкий почасовой запрос', url: '/api/v1/forecast?granularity=hour', status: 422, code: 'range_too_wide' },
  { name: 'Неверная детализация', url: '/api/v1/forecast?granularity=week', status: 422, code: 'validation_error' },
  { name: 'Мусор вместо даты', url: '/api/v1/forecast?start=вчера', status: 422, code: 'validation_error' },
  { name: 'Экспорт: неверный формат', url: '/api/v1/export?format=pdf', status: 422, code: 'validation_error' },
  { name: 'Коэффициент вне границ', url: '/api/v1/forecast/adjusted', body: { factors: { weather: 3 } }, status: 422, code: 'validation_error' },
  { name: 'Правило: неизвестный маршрут', url: '/api/v1/forecast/adjusted', body: { rules: [{ start: '2025-11-01', end: '2025-11-02', factor: 1, routes: [99] }] }, status: 404, code: 'route_not_found' },
  { name: 'Поправки: неизвестное название', url: '/api/v1/forecast?corrections=nope', status: 422, code: 'unknown_correction' },
  { name: 'Поправки к истории', url: '/api/v1/export?kind=history&corrections=regime', status: 422, code: 'corrections_forecast_only' },
  { name: 'Остановки: маршрут без справочника', url: '/api/v1/stops?route=17', status: 404, code: 'stops_not_available' },
  { name: 'Остановки: не указан маршрут', url: '/api/v1/stops/flow', status: 422, code: 'validation_error' },
  { name: 'Остановки: неизвестная остановка', url: '/api/v1/stops/000/series', status: 404, code: 'stop_not_found' },
  { name: 'Приём: пустой пакет', url: '/api/v1/ingest/validations', body: { records: [] }, status: 422, code: 'validation_error' },
  { name: 'Приём: без ключа на защищённом сервере', url: '/api/v1/ingest/validations', body: { records: [{ tran_date_time: '2025-11-03 08:00:00', validation_result: 1, ngpt_route: '7 трамвай' }] }, status: 401, code: 'unauthorized', noKey: true, onlyGuarded: true },
  { name: 'Приём: нет обязательных полей', url: '/api/v1/ingest/validations', body: { records: [{ foo: 1 }] }, status: 422, code: 'missing_fields' },
]

function ErrorsTab({ apiKey, guarded }: { apiKey: string; guarded: boolean }) {
  const [out, setOut] = useState<Row[]>([])
  const cases = CASES.filter((c) => guarded || !c.onlyGuarded)
  const run = async () => {
    setOut([])
    const rows: Row[] = []
    for (const c of cases) {
      const auth: Record<string, string> = apiKey && !c.noKey ? { 'X-API-Key': apiKey } : {}
      const r = c.body ? await post(c.url, c.body, auth) : await call(c.url)
      const d = (typeof r.data === 'object' && r.data ? r.data : {}) as { detail?: string; code?: string }
      rows.push({ проверка: c.name, ожидали: `${c.status} ${c.code}`, получили: `${r.status} ${d.code ?? ''}`, результат: r.status === c.status && d.code === c.code ? '✓' : '✗ ОШИБКА', сообщение: d.detail ?? '' })
      setOut([...rows])
    }
  }
  return (
    <>
      <p className="t-note">Отправляет заведомо неверные запросы и сверяет статус и код ошибки с ожидаемыми.{guarded && !apiKey ? ' Сервер защищён ключом: введите X-API-Key в шапке, иначе проверки приёма вернут 401.' : ''}</p>
      <div className="t-form"><button onClick={run}>Запустить все проверки</button>{out.length > 0 && <b>{out.filter((r) => r.результат === '✓').length} из {cases.length} прошли</b>}</div>
      <Table rows={out} />
    </>
  )
}

const TABS = ['Ряды', 'Экспорт', 'Коэффициенты', 'Год', 'Остановки', 'Диспетчер', 'Приём данных', 'Ошибки'] as const

export default function Tester() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('Ряды')
  const [routes, setRoutes] = useState<number[]>([])
  const [health, setHealth] = useState<Result | null>(null)
  const [apiKey, setApiKey] = useState('')
  useEffect(() => {
    call('/api/v1/health').then(setHealth)
    call('/api/v1/routes').then((r) => { if (r.status === 200) setRoutes((r.data as RouteInfo[]).map((x) => x.id)) })
  }, [])
  const h = health && health.status === 200 ? (health.data as { version: string; history_period: string[]; forecast_period: string[]; routes: number; ingest_protected?: boolean }) : null
  return (
    <div className="t-root">
      <style>{CSS}</style>
      <header>
        <h1>Проверка API</h1>
        <div className="t-muted">
          {h ? <>сервис v{h.version} · история {h.history_period[0]} — {h.history_period[1]} · прогноз {h.forecast_period[0]} — {h.forecast_period[1]} · маршрутов {h.routes}</>
             : health ? <span className="t-error">Сервис недоступен (статус {health.status || 'нет ответа'})</span> : 'Подключение…'}
        </div>
        <label className="t-field" style={{ margin: '10px 0' }}><span>X-API-Key для приёма данных{h?.ingest_protected ? ' (сервер защищён ключом)' : ' (на сервере не задан)'}</span><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="не задан" autoComplete="off" style={{ maxWidth: 320 }} /></label>
        <nav><a href="#/">← Дашборд</a><a href={`${API}/docs`} target="_blank" rel="noreferrer">Swagger /docs</a></nav>
      </header>
      <div className="t-tabs">{TABS.map((t) => <button key={t} className={t === tab ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      <main>
        {tab === 'Ряды' && <SeriesTab routes={routes} />}
        {tab === 'Экспорт' && <ExportTab routes={routes} />}
        {tab === 'Коэффициенты' && <AdjustTab routes={routes} />}
        {tab === 'Год' && <YearTab routes={routes} />}
        {tab === 'Диспетчер' && <DispatchTab routes={routes} />}
        {tab === 'Остановки' && <StopsTab />}
        {tab === 'Приём данных' && <IngestTab apiKey={apiKey} />}
        {tab === 'Ошибки' && <ErrorsTab apiKey={apiKey} guarded={!!h?.ingest_protected} />}
      </main>
    </div>
  )
}

const CSS = `
.t-root{max-width:1100px;margin:0 auto;padding:20px 16px 60px;color:#20283a;font-size:14px}
.t-root h1{margin:0 0 4px;font-size:24px}.t-root h3{margin:22px 0 6px;font-size:15px}
.t-root header nav{display:flex;gap:16px;margin:10px 0 14px}.t-root a{color:#2e6bff;text-decoration:none}
.t-muted{color:#8c95a7;font-size:12px}.t-note{background:#f0f4ff;border-radius:8px;padding:8px 12px;margin:10px 0}
.t-tabs{display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid #edf0f5;padding-bottom:10px;margin-bottom:14px}
.t-tabs button{border:1px solid #dfe4ee;background:#fff;border-radius:8px;padding:7px 13px}.t-tabs .on{background:#2e6bff;color:#fff;border-color:#2e6bff}
.t-form{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:10px 0}
.t-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#5b6577}
.t-field input,.t-field select,.t-root textarea{border:1px solid #dfe4ee;border-radius:8px;padding:7px 9px;background:#fff;color:#20283a}
.t-check{display:flex;gap:6px;align-items:center;padding-bottom:8px}
.t-form>button{background:#2e6bff;color:#fff;border:0;border-radius:8px;padding:9px 16px;font-weight:600}.t-form>button.ghost{background:#eef2fb;color:#2e6bff}
.t-panel{border:1px solid #edf0f5;border-radius:10px;padding:10px 12px;margin:10px 0;background:#fff}
.t-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.t-line code{word-break:break-all}
.t-badge{border-radius:6px;padding:2px 8px;font-weight:700;color:#fff}.t-badge.ok{background:#00a78b}.t-badge.bad{background:#e65f73}
.t-error{color:#c0364b;margin-top:6px}.t-panel pre{max-height:320px;overflow:auto;background:#f6f7fb;padding:10px;border-radius:8px;font-size:12px}
.t-scroll{overflow:auto;max-height:420px}.t-root table{border-collapse:collapse;width:100%;font-size:12px}
.t-root th,.t-root td{border-bottom:1px solid #edf0f5;padding:5px 8px;text-align:left;white-space:nowrap}.t-root th{position:sticky;top:0;background:#f6f7fb}
.t-click{cursor:pointer}.t-click:hover{background:#f0f4ff}
.t-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.t-cards div{border:1px solid #edf0f5;border-radius:10px;padding:10px 12px;background:#fff}.t-cards b{display:block;font-size:20px}.t-cards span{color:#8c95a7;font-size:12px}
.t-area{width:100%;height:220px;font-family:ui-monospace,Menlo,monospace;font-size:12px}
`
