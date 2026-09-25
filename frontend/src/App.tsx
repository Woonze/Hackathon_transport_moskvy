import { useEffect, useMemo, useState } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, CalendarDays, ChevronDown, Clock3, MapPin, Menu, Route as RouteIcon, Sparkles, TramFront, Users, Zap } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip as MapTooltip } from 'react-leaflet'
import type { Feature, FeatureCollection, LineString, MultiLineString } from 'geojson'
import 'leaflet/dist/leaflet.css'
import './styles.css'

type Flow = { route: number; date: string; hour: number; passengers: number }
type TramRoute = { id: number; name: string; historical_total: number; forecast_total: number }
type WeekdayAverage = { route: number; weekday: number; passengers: number }
type RouteFeature = Feature<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
type RouteGeo = FeatureCollection<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>

const API = import.meta.env.VITE_API_URL ?? ''
const routeColors: Record<number, string> = { 1: '#2e6bff', 5: '#f0a339', 7: '#00a78b', 11: '#8556e8', 12: '#e65f73', 17: '#62748b', 25: '#14a5c7', 26: '#dc8b23', 28: '#b15cb7', 50: '#46804c' }
const format = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))
const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

function dateLabel(value: string, long = false) {
  const d = new Date(`${value}T12:00:00`)
  return new Intl.DateTimeFormat('ru-RU', long ? { day: 'numeric', month: 'long', weekday: 'long' } : { day: 'numeric', month: 'short' }).format(d)
}

function App() {
  const [forecast, setForecast] = useState<Flow[]>([])
  const [dateForecast, setDateForecast] = useState<Flow[]>([])
  const [weekdayAverages, setWeekdayAverages] = useState<WeekdayAverage[]>([])
  const [routes, setRoutes] = useState<TramRoute[]>([])
  const [geo, setGeo] = useState<RouteGeo>({ type: 'FeatureCollection', features: [] })
  const [month, setMonth] = useState(11)
  const [route, setRoute] = useState<number | 'all'>('all')
  const [selectedDate, setSelectedDate] = useState('2025-11-01')
  const [mode, setMode] = useState<'days' | 'hours'>('days')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      fetch(`${API}/api/history/weekday-average`).then((r) => { if (!r.ok) throw new Error('Сводка истории недоступна'); return r.json() }),
      fetch(`${API}/api/routes`).then((r) => { if (!r.ok) throw new Error('Маршруты недоступны'); return r.json() }),
      fetch(`${API}/api/map`).then((r) => r.ok ? r.json() : { type: 'FeatureCollection', features: [] }),
    ]).then(([hist, routeList, routeGeo]) => {
      setWeekdayAverages(hist); setRoutes(routeList); setGeo(routeGeo)
    }).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    const start = `2025-${String(month).padStart(2, '0')}-01`
    const end = `2025-${String(month).padStart(2, '0')}-${String(new Date(2025, month, 0).getDate()).padStart(2, '0')}`
    setLoading(true)
    Promise.all([
      fetch(`${API}/api/forecast?start=${start}&end=${end}&granularity=day`).then((r) => { if (!r.ok) throw new Error('Прогноз недоступен'); return r.json() }),
      fetch(`${API}/api/forecast?start=${selectedDate}&end=${selectedDate}&granularity=hour`).then((r) => { if (!r.ok) throw new Error('Почасовой прогноз недоступен'); return r.json() }),
    ]).then(([monthRows, dateRows]) => {
      setForecast(monthRows.map((row: Omit<Flow, 'hour'>) => ({ ...row, hour: 0 })))
      setDateForecast(dateRows)
      setLoading(false)
    }).catch((e: Error) => { setError(e.message); setLoading(false) })
  }, [month, selectedDate])

  const visibleForecast = useMemo(() => forecast.filter((row) => Number(row.date.slice(5, 7)) === month && (route === 'all' || row.route === route)), [forecast, month, route])
  const dateRows = useMemo(() => dateForecast.filter((row) => route === 'all' || row.route === route), [dateForecast, route])
  const dayTotal = dateRows.reduce((sum, row) => sum + row.passengers, 0)
  const hourlyDayRows = useMemo(() => Array.from({ length: 24 }, (_, hour) => ({ route: 0, date: selectedDate, hour, passengers: dateRows.filter((row) => row.hour === hour).reduce((sum, row) => sum + row.passengers, 0) })), [dateRows, selectedDate])
  const allMonthTotal = visibleForecast.reduce((sum, row) => sum + row.passengers, 0)
  const peak = hourlyDayRows.reduce((best, row) => row.passengers > best.passengers ? row : best, { hour: 0, passengers: 0 } as Flow)
  const recentWeekdayBaseline = useMemo(() => {
    if (!dateRows.length) return 0
    const weekday = (new Date(`${selectedDate}T12:00:00`).getDay() + 6) % 7
    return weekdayAverages.filter((row) => row.weekday === weekday && (route === 'all' || row.route === route)).reduce((sum, row) => sum + row.passengers, 0)
  }, [dateRows, selectedDate, route, weekdayAverages])
  const delta = recentWeekdayBaseline ? (dayTotal / recentWeekdayBaseline - 1) * 100 : 0

  const dailyChart = useMemo(() => {
    const byDate = new Map<string, number>()
    visibleForecast.forEach((row) => byDate.set(row.date, (byDate.get(row.date) ?? 0) + row.passengers))
    return [...byDate].map(([date, passengers]) => ({ date, label: dateLabel(date), passengers })).sort((a, b) => a.date.localeCompare(b.date))
  }, [visibleForecast])
  const hourlyChart = useMemo(() => hourlyDayRows.map((row) => ({ ...row, label: `${String(row.hour).padStart(2, '0')}:00` })), [hourlyDayRows])
  const routeRanking = useMemo(() => routes.map((item) => ({ ...item, value: visibleForecast.filter((row) => row.route === item.id).reduce((sum, row) => sum + row.passengers, 0) })).sort((a, b) => b.value - a.value), [routes, visibleForecast])
  const mapFeatures = useMemo(() => ({ ...geo, features: (geo.features as RouteFeature[]).filter((feature) => route === 'all' || feature.properties?.route === route) }), [geo, route])
  const exportCsv = async () => {
    const start = `2025-${String(month).padStart(2, '0')}-01`
    const end = `2025-${String(month).padStart(2, '0')}-${String(new Date(2025, month, 0).getDate()).padStart(2, '0')}`
    const routeQuery = route === 'all' ? '' : `&route=${route}`
    try {
      const response = await fetch(`${API}/api/forecast?start=${start}&end=${end}&granularity=hour${routeQuery}`)
      if (!response.ok) throw new Error('Не удалось получить CSV')
      const rows = await response.json() as Flow[]
      const csv = ['route;date;hour;prediction', ...rows.map((row) => `${row.route};${row.date};${row.hour};${row.passengers}`)]
      const blob = new Blob(['\uFEFF' + csv.join('\n')], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tramway_forecast_${month}.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) { setError((e as Error).message) }
  }

  useEffect(() => {
    const dayCount = new Date(2025, month, 0).getDate()
    if (Number(selectedDate.slice(5, 7)) !== month) setSelectedDate(`2025-${String(month).padStart(2, '0')}-01`)
    else if (Number(selectedDate.slice(8, 10)) > dayCount) setSelectedDate(`2025-${String(month).padStart(2, '0')}-${String(dayCount).padStart(2, '0')}`)
  }, [month, selectedDate])

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><TramFront size={21} strokeWidth={2.2} /></div><div><strong>МОС.ТРАМ</strong><span>АНАЛИТИКА ПОТОКА</span></div></div>
      <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <button className="nav-item active"><Activity size={18} /><span>Обзор пассажиропотока</span><span className="active-dot" /></button>
      <button className="nav-item"><RouteIcon size={18} /><span>Маршруты</span><span className="nav-soon">10</span></button>
      <button className="nav-item"><CalendarDays size={18} /><span>История данных</span></button>
      <div className="side-bottom"><div className="system-card"><div className="system-row"><span className="status-light" /> Модель работает</div><p>Обновление прогноза<br />25 сентября, 12:40</p><div className="system-foot"><span>Версия 1.0</span><span className="spark"><Sparkles size={13} /> ML</span></div></div><div className="user-row"><div className="avatar">ЕД</div><div><strong>Диспетчер ЕДЦ</strong><span>Москва · Трамвай</span></div><Menu size={17} className="user-menu" /></div></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="crumbs">Аналитика <span>/</span> <b>Пассажиропоток</b></div><div className="top-actions"><div className="live-pill"><span className="live-dot" /> Прогноз готов</div><button className="icon-button" title="Справка"><span>?</span></button><div className="top-avatar">ЕД</div></div></header>
      <div className="content-wrap">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> ПЛАНИРОВАНИЕ · НОЯБРЬ—ДЕКАБРЬ 2025</div><h1>Пассажиропоток трамваев</h1><p>Прогноз загрузки маршрутов по часам и дням для оперативного планирования</p></div><div className="heading-actions"><button className="secondary-button" onClick={exportCsv}><span className="export-icon">↧</span> Экспорт отчёта</button></div></section>
        <section className="toolbar"><div className="toolbar-group"><div className="toolbar-caption">ПЕРИОД ПРОГНОЗА</div><div className="month-switch"><button className={month === 11 ? 'selected' : ''} onClick={() => setMonth(11)}>Ноябрь</button><button className={month === 12 ? 'selected' : ''} onClick={() => setMonth(12)}>Декабрь</button></div></div><div className="toolbar-separator" /><label className="select-wrap"><span className="toolbar-caption">МАРШРУТ</span><div className="select-control"><RouteIcon size={16} /><select value={route} onChange={(e) => setRoute(e.target.value === 'all' ? 'all' : Number(e.target.value))}><option value="all">Все маршруты</option>{routes.map((item) => <option key={item.id} value={item.id}>Трамвай {item.id}</option>)}</select><ChevronDown size={15} /></div></label><div className="toolbar-separator" /><label className="select-wrap date-select"><span className="toolbar-caption">ДАТА ДЛЯ ДЕТАЛЬНОГО ПРОСМОТРА</span><div className="select-control"><CalendarDays size={16} /><select value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}>{Array.from({ length: new Date(2025, month, 0).getDate() }, (_, i) => { const d = `2025-${String(month).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`; return <option key={d} value={d}>{dateLabel(d, true)}</option> })}</select><ChevronDown size={15} /></div></label><div className="updated-label"><span className="live-dot" /> Последнее обновление<br /><b>25 сен, 12:40</b></div></section>

        {error && <div className="error-banner">Не удалось загрузить данные: {error}. Убедитесь, что API запущен на порту 8000.</div>}
        {loading && <div className="loading-card"><div className="loader" /> Загружаем прогноз и справочники…</div>}

        <section className="kpi-grid">
          <article className="kpi-card primary-kpi"><div className="kpi-top"><div className="kpi-icon blue"><Users size={18} /></div><span className="kpi-tag"><Sparkles size={12} /> ПРОГНОЗ</span></div><div className="kpi-label">Посадки за выбранный день</div><div className="kpi-value">{format(dayTotal)} <small>пасс.</small></div><div className="kpi-foot"><span className={delta >= 0 ? 'trend positive' : 'trend negative'}>{delta >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}{Math.abs(delta).toFixed(1)}%</span><span>к среднему за похожий день</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon purple"><Clock3 size={18} /></div><span className="kpi-tag muted">ПИКОВАЯ НАГРУЗКА</span></div><div className="kpi-label">Час максимального потока</div><div className="kpi-value">{String(peak.hour).padStart(2, '0')}:00 <small>— {String((peak.hour + 1) % 24).padStart(2, '0')}:00</small></div><div className="kpi-foot"><span className="foot-dot purple-dot" /> <b>{format(peak.passengers)}</b><span>посадок за час</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon mint"><CalendarDays size={18} /></div><span className="kpi-tag muted">{monthNames[month - 1].toUpperCase()} 2025</span></div><div className="kpi-label">Прогноз за месяц</div><div className="kpi-value">{format(allMonthTotal)} <small>пасс.</small></div><div className="kpi-foot"><span className="foot-dot green-dot" /> <b>{dailyChart.length}</b><span>дней в расчёте</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon orange"><Zap size={18} /></div><span className="kpi-tag muted">ГОРИЗОНТ</span></div><div className="kpi-label">Детализация прогноза</div><div className="kpi-value">24 <small>часа</small></div><div className="kpi-foot"><span className="foot-dot orange-dot" /> <b>10</b><span>трамвайных маршрутов</span></div></article>
        </section>

        <section className="main-grid">
          <article className="panel map-panel"><div className="panel-heading"><div><div className="panel-title">Маршруты на карте</div><div className="panel-subtitle">География остановок и схема движения</div></div><div className="map-badge"><MapPin size={13} /> МОСКВА</div></div><div className="map-frame"><MapContainer center={[55.7558, 37.6173]} zoom={10} scrollWheelZoom={false} className="leaflet-map"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /><GeoJSON key={`${route}-${mapFeatures.features.length}`} data={mapFeatures as RouteGeo} style={(feature) => ({ color: routeColors[feature?.properties?.route ?? 1] ?? '#4770eb', weight: 4, opacity: 0.78, lineCap: 'round', lineJoin: 'round' })} onEachFeature={(feature, layer) => { const props = feature.properties as RouteFeature['properties']; layer.bindTooltip(`Трамвай ${props?.route ?? ''} · ${props?.stop_count ?? 0} остановок`, { sticky: true }) }} />{(mapFeatures.features as RouteFeature[]).flatMap((feature, index) => (feature.geometry.type === 'LineString' ? feature.geometry.coordinates : feature.geometry.coordinates[0]).filter((_, i) => i % 2 === 0).map((coord, i) => <CircleMarker key={`${index}-${i}`} center={[coord[1], coord[0]]} radius={3.2} pathOptions={{ color: '#fff', weight: 1.4, fillColor: routeColors[feature.properties?.route ?? 1], fillOpacity: 0.96 }}><MapTooltip>{feature.properties?.stops?.[i * 2] ?? `Остановка ${i + 1}`}</MapTooltip></CircleMarker>))}</MapContainer><div className="map-legend"><span className="legend-line" /> Маршрут <span className="legend-stop" /> Остановка</div></div><div className="map-note"><span className="note-info">i</span><span>Схема построена по доступным координатам остановок из справочника. Показаны маршруты 1, 5, 7, 11 и 12.</span></div></article>

          <article className="panel flow-panel"><div className="panel-heading flow-heading"><div><div className="panel-title">Динамика пассажиропотока</div><div className="panel-subtitle">{mode === 'days' ? 'Суммарный прогноз по дням месяца' : 'Почасовой прогноз на выбранную дату'}</div></div><div className="segmented"><button className={mode === 'days' ? 'active' : ''} onClick={() => setMode('days')}>По дням</button><button className={mode === 'hours' ? 'active' : ''} onClick={() => setMode('hours')}>По часам</button></div></div><div className="chart-summary"><div><strong>{mode === 'days' ? format(allMonthTotal) : format(dayTotal)}</strong><span>{mode === 'days' ? 'посадок за месяц' : `посадок · ${dateLabel(selectedDate)}`}</span></div><div className="chart-period"><span className="chart-key" /> Прогноз</div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={mode === 'days' ? dailyChart : hourlyChart} margin={{ top: 12, right: 8, left: -14, bottom: 0 }}><defs><linearGradient id="flowGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#537dff" stopOpacity={0.2} /><stop offset="100%" stopColor="#537dff" stopOpacity={0.015} /></linearGradient></defs><CartesianGrid stroke="#edf0f6" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 11 }} interval={mode === 'days' ? 6 : 3} minTickGap={16} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 11 }} tickFormatter={(n) => n >= 1000 ? `${(n / 1000).toFixed(0)}к` : n} /><Tooltip contentStyle={{ border: '1px solid #edf0f6', borderRadius: 12, boxShadow: '0 8px 28px #26395c17', fontSize: 12 }} formatter={(value) => [`${format(Number(value))} пассажиров`, 'Прогноз']} labelStyle={{ color: '#647087', marginBottom: 4 }} /><Area type="monotone" dataKey="passengers" stroke="#4f75f3" strokeWidth={2.5} fill="url(#flowGradient)" activeDot={{ r: 5, strokeWidth: 3, stroke: '#fff' }} /></AreaChart></ResponsiveContainer></div><div className="chart-footer"><span><span className="foot-dot blue-dot" /> Средний прогноз по выбранному периоду</span><button onClick={() => setMode(mode === 'days' ? 'hours' : 'days')}>Подробнее <span>↗</span></button></div></article>
        </section>

        <section className="bottom-grid"><article className="panel ranking-panel"><div className="panel-heading"><div><div className="panel-title">Загрузка маршрутов</div><div className="panel-subtitle">Прогноз посадок · {monthNames[month - 1].toLowerCase()} 2025</div></div><button className="text-action" onClick={() => setRoute('all')}>Все маршруты <span>→</span></button></div><div className="ranking-list">{routeRanking.map((item, index) => <button className={`ranking-row ${route === item.id ? 'chosen' : ''}`} key={item.id} onClick={() => setRoute(route === item.id ? 'all' : item.id)}><span className="rank-num">{String(index + 1).padStart(2, '0')}</span><span className="route-number" style={{ color: routeColors[item.id], background: `${routeColors[item.id]}13` }}>{item.id}</span><span className="rank-bar-track"><span className="rank-bar-fill" style={{ width: `${routeRanking[0]?.value ? item.value / routeRanking[0].value * 100 : 0}%`, background: routeColors[item.id] }} /></span><span className="rank-value">{format(item.value)}</span><span className="rank-label">посадок</span></button>)}</div><div className="ranking-footer">Выберите маршрут, чтобы отфильтровать карту и прогноз</div></article><article className="panel day-panel"><div className="panel-heading"><div><div className="panel-title">Почасовой прогноз</div><div className="panel-subtitle">{dateLabel(selectedDate, true)}</div></div><div className="date-chip"><CalendarDays size={14} /> {monthNames[month - 1]}</div></div><div className="hour-list">{hourlyDayRows.filter((row) => row.hour >= 5 && row.hour <= 23).map((row) => { const max = Math.max(...hourlyDayRows.map((r) => r.passengers), 1); return <div className={`hour-row ${row.hour === peak.hour ? 'peak-row' : ''}`} key={row.hour}><span className="hour-time">{String(row.hour).padStart(2, '0')}:00</span><span className="hour-bar-bg"><span className="hour-bar" style={{ width: `${row.passengers / max * 100}%` }} /></span><span className="hour-value">{format(row.passengers)}</span>{row.hour === peak.hour && <span className="peak-label">ПИК</span>}</div> })}</div><div className="day-total"><span>Итого за день</span><strong>{format(dayTotal)} <small>посадок</small></strong></div></article></section>
        <footer className="page-footer"><span>Московский городской транспорт <b>·</b> Единый диспетчерский центр</span><span><span className="live-dot" /> Данные прогноза · модель временных рядов</span></footer>
      </div>
    </main>
  </div>
}

export default App
