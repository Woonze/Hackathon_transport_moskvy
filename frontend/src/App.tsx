import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, Download, FlaskConical, CalendarDays, ChevronDown, Gauge, MapPinned, Route as RouteIcon, Search, Sparkles, TramFront, Users } from 'lucide-react'
import type { FeatureCollection, LineString, MultiLineString } from 'geojson'
import './styles.css'
import type { ForecastPeriod } from './panels/FlowChart'
import type { MapStop } from './panels/OverviewMap'

const Horizons = lazy(() => import('./panels/Horizons'))
const Coefficients = lazy(() => import('./panels/Coefficients'))
const OverviewMap = lazy(() => import('./panels/OverviewMap'))
const FlowChart = lazy(() => import('./panels/FlowChart'))
const StopHourly = lazy(() => import('./panels/StopHourly'))

type Flow = { route: number; date: string; hour: number; passengers: number }
type TramRoute = { id: number; name: string; historical_total: number; forecast_total: number }
type WeekdayAverage = { route: number; weekday: number; passengers: number }
type Health = { status: 'ok' | 'error'; version: string; history_period?: [string, string] }
type RouteGeo = FeatureCollection<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
type EventRisk = 'critical' | 'warning' | 'info'
type MapMode = 'passengers' | 'overload' | 'deviation' | 'forecast'
type StopFlow = { stops: Array<MapStop & { boardings: number; share: number }> }
type StopSeries = { data: Array<{ date?: string; hour?: number; passengers: number }> }
type StopInsight = { boardings: number; share: number; hourly: Array<{ hour: number; passengers: number }>; daily: Array<{ date: string; passengers: number }> }

const API = import.meta.env.VITE_API_URL ?? ''
const FORECAST_START = '2025-11-01'
const FORECAST_END = '2025-12-31'
const WEEK_LAST_START = '2025-12-25'
const routeColors: Record<number, string> = { 1: '#2e6bff', 5: '#f0a339', 7: '#00a78b', 11: '#8556e8', 12: '#e65f73', 17: '#62748b', 25: '#14a5c7', 26: '#dc8b23', 28: '#b15cb7', 50: '#46804c' }
const format = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))
const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

function dateLabel(value: string, long = false) {
  const d = new Date(`${value}T12:00:00`)
  return new Intl.DateTimeFormat('ru-RU', long ? { day: 'numeric', month: 'long', weekday: 'long' } : { day: 'numeric', month: 'short' }).format(d)
}

function addDays(value: string, days: number) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

function minDate(left: string, right: string) {
  return left < right ? left : right
}

function App() {
  const [forecast, setForecast] = useState<Flow[]>([])
  const [dateForecast, setDateForecast] = useState<Flow[]>([])
  const [weekdayAverages, setWeekdayAverages] = useState<WeekdayAverage[]>([])
  const [routes, setRoutes] = useState<TramRoute[]>([])
  const [geo, setGeo] = useState<RouteGeo>({ type: 'FeatureCollection', features: [] })
  const [stops, setStops] = useState<MapStop[]>([])
  const [selectedStop, setSelectedStop] = useState<MapStop | null>(null)
  const [stopInsight, setStopInsight] = useState<StopInsight | null>(null)
  const [stopInsightError, setStopInsightError] = useState('')
  const [stopInsightLoading, setStopInsightLoading] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [month, setMonth] = useState(11)
  const [route, setRoute] = useState<number | 'all'>('all')
  const [navSection, setNavSection] = useState<'overview' | 'routes' | 'history'>('overview')
  const [selectedDate, setSelectedDate] = useState('2025-11-01')
  const [mode, setMode] = useState<ForecastPeriod>('month')
  const [mapMode, setMapMode] = useState<MapMode>('passengers')
  const [eventFilter, setEventFilter] = useState<'all' | EventRisk>('all')
  const [eventSort, setEventSort] = useState<'priority' | 'load' | 'route'>('priority')
  const [detailTab, setDetailTab] = useState<'overview' | 'load' | 'forecast' | 'stop'>('forecast')
  const [search, setSearch] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const [dailyLoading, setDailyLoading] = useState(true)
  const [hourlyLoading, setHourlyLoading] = useState(true)
  const [referenceError, setReferenceError] = useState('')
  const [forecastError, setForecastError] = useState('')
  const [hourlyError, setHourlyError] = useState('')
  const error = referenceError || forecastError || hourlyError
  const loading = dailyLoading || hourlyLoading
  const selectedRouteHasNoHistory = route !== 'all' && routes.find((item) => item.id === route)?.historical_total === 0

  useEffect(() => {
    const controller = new AbortController()
    setReferenceError('')
    Promise.all([
      fetch(`${API}/api/history/weekday-average`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Сводка истории недоступна'); return r.json() }),
      fetch(`${API}/api/routes`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Маршруты недоступны'); return r.json() }),
      fetch(`${API}/api/map`, { signal: controller.signal }).then((r) => r.ok ? r.json() : { type: 'FeatureCollection', features: [] }),
      fetch(`${API}/api/v1/stops`, { signal: controller.signal }).then((r) => r.ok ? r.json() : { stops: [] }),
      fetch(`${API}/api/health`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Сервис недоступен'); return r.json() }),
    ]).then(([hist, routeList, routeGeo, stopCatalog, serviceHealth]) => {
      setWeekdayAverages(hist); setRoutes(routeList); setGeo(routeGeo); setStops(stopCatalog.stops ?? []); setHealth(serviceHealth)
    }).catch((e: Error) => { if (e.name !== 'AbortError') setReferenceError(e.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setForecastError('')
    setDailyLoading(true)
    fetch(`${API}/api/forecast?start=${FORECAST_START}&end=${FORECAST_END}&granularity=day`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error('Прогноз недоступен'); return response.json() })
      .then((rows: Omit<Flow, 'hour'>[]) => setForecast(rows.map((row) => ({ ...row, hour: 0 }))))
      .catch((e: Error) => { if (e.name !== 'AbortError') setForecastError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setDailyLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setHourlyError('')
    setHourlyLoading(true)
    fetch(`${API}/api/forecast?start=${selectedDate}&end=${selectedDate}&granularity=hour`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error('Почасовой прогноз недоступен'); return response.json() })
      .then((rows: Flow[]) => setDateForecast(rows))
      .catch((e: Error) => { if (e.name !== 'AbortError') setHourlyError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setHourlyLoading(false) })
    return () => controller.abort()
  }, [selectedDate])

  useEffect(() => {
    if (!selectedStop) {
      setStopInsight(null)
      setStopInsightError('')
      setStopInsightLoading(false)
      return
    }
    const controller = new AbortController()
    const monthStart = `${selectedDate.slice(0, 7)}-01`
    const monthEnd = `${selectedDate.slice(0, 7)}-${String(new Date(Number(selectedDate.slice(0, 4)), Number(selectedDate.slice(5, 7)), 0).getDate()).padStart(2, '0')}`
    const stopId = encodeURIComponent(selectedStop.stop_id)
    const routeId = selectedStop.route
    setStopInsight(null)
    setStopInsightError('')
    setStopInsightLoading(true)
    Promise.all([
      fetch(`${API}/api/v1/stops/flow?route=${routeId}&kind=forecast&start=${selectedDate}&end=${selectedDate}&hour_from=0&hour_to=23`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Нагрузка остановки недоступна'); return r.json() as Promise<StopFlow> }),
      fetch(`${API}/api/v1/stops/${stopId}/series?kind=forecast&start=${selectedDate}&end=${selectedDate}&granularity=hour&route=${routeId}`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Почасовой прогноз остановки недоступен'); return r.json() as Promise<StopSeries> }),
      fetch(`${API}/api/v1/stops/${stopId}/series?kind=forecast&start=${monthStart}&end=${monthEnd}&granularity=day&route=${routeId}`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Месячный прогноз остановки недоступен'); return r.json() as Promise<StopSeries> }),
    ]).then(([flow, hourly, daily]) => {
      const flowStop = flow.stops.find((item) => item.stop_id === selectedStop.stop_id && item.direction === selectedStop.direction)
        ?? flow.stops.find((item) => item.stop_id === selectedStop.stop_id)
      setStopInsight({
        boardings: flowStop?.boardings ?? hourly.data.reduce((sum, item) => sum + item.passengers, 0),
        share: flowStop?.share ?? selectedStop.boarding_share,
        hourly: hourly.data.map((item) => ({ hour: item.hour ?? 0, passengers: item.passengers })),
        daily: daily.data.map((item) => ({ date: item.date ?? '', passengers: item.passengers })),
      })
    }).catch((e: Error) => { if (e.name !== 'AbortError') setStopInsightError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setStopInsightLoading(false) })
    return () => controller.abort()
  }, [selectedStop, selectedDate])

  useEffect(() => {
    if (selectedStop && route !== selectedStop.route) {
      setSelectedStop(null)
      if (detailTab === 'stop') setDetailTab('overview')
    }
  }, [route, selectedStop, detailTab])

  const monthForecast = useMemo(() => forecast.filter((row) => Number(row.date.slice(5, 7)) === month), [forecast, month])
  const visibleForecast = useMemo(() => monthForecast.filter((row) => route === 'all' || row.route === route), [monthForecast, route])
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
  const weekEnd = minDate(addDays(selectedDate, 6), FORECAST_END)
  const weeklyChart = useMemo(() => {
    const byDate = new Map<string, number>()
    forecast.filter((row) => row.date >= selectedDate && row.date <= weekEnd && (route === 'all' || row.route === route))
      .forEach((row) => byDate.set(row.date, (byDate.get(row.date) ?? 0) + row.passengers))
    return [...byDate].map(([date, passengers]) => ({ date, label: dateLabel(date), passengers })).sort((a, b) => a.date.localeCompare(b.date))
  }, [forecast, route, selectedDate, weekEnd])
  const weeklyTotal = weeklyChart.reduce((sum, row) => sum + row.passengers, 0)
  const chartData = mode === 'day' ? hourlyChart : mode === 'week' ? weeklyChart : dailyChart
  const chartTotal = mode === 'day' ? dayTotal : mode === 'week' ? weeklyTotal : allMonthTotal
  const chartCaption = mode === 'day'
    ? `посадок · ${dateLabel(selectedDate)}`
    : mode === 'week'
      ? `посадок · ${dateLabel(selectedDate)} — ${dateLabel(weekEnd)}`
      : `посадок за ${monthNames[month - 1].toLowerCase()}`
  const routeRanking = useMemo(() => routes.map((item) => ({ ...item, value: monthForecast.filter((row) => row.route === item.id).reduce((sum, row) => sum + row.passengers, 0) })).sort((a, b) => b.value - a.value), [routes, monthForecast])
  const historyMonths = useMemo(() => {
    if (!health?.history_period) return 10
    const [sy, sm] = health.history_period[0].slice(0, 7).split('-').map(Number)
    const [ey, em] = health.history_period[1].slice(0, 7).split('-').map(Number)
    return (ey - sy) * 12 + (em - sm) + 1
  }, [health])
  const routeEvents = useMemo(() => routeRanking.map((item) => {
    const historicalMonthAverage = item.historical_total / historyMonths
    const change = historicalMonthAverage > 0 ? (item.value / historicalMonthAverage - 1) * 100 : null
    const risk: EventRisk = change !== null && change >= 8 ? 'critical' : change !== null && change >= 2 ? 'warning' : 'info'
    return { ...item, change, risk }
  }), [routeRanking, historyMonths])
  const eventCounts = useMemo(() => ({
    critical: routeEvents.filter((item) => item.risk === 'critical').length,
    warning: routeEvents.filter((item) => item.risk === 'warning').length,
  }), [routeEvents])
  const matchingStopRoutes = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ru-RU')
    if (!query) return new Set<number>()
    return new Set(geo.features.filter((feature) => feature.properties.stops.some((stop) => stop.toLocaleLowerCase('ru-RU').includes(query))).map((feature) => feature.properties.route))
  }, [geo, search])
  const visibleEvents = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ru-RU')
    const priority: Record<EventRisk, number> = { critical: 0, warning: 1, info: 2 }
    return routeEvents
      .filter((item) => eventFilter === 'all' || item.risk === eventFilter)
      .filter((item) => !query || String(item.id).includes(query) || item.name.toLocaleLowerCase('ru-RU').includes(query) || matchingStopRoutes.has(item.id))
      .sort((a, b) => eventSort === 'route' ? a.id - b.id : eventSort === 'load' ? b.value - a.value : priority[a.risk] - priority[b.risk] || b.value - a.value)
  }, [routeEvents, eventFilter, eventSort, search, matchingStopRoutes])
  const mapMetrics = useMemo(() => Object.fromEntries(routeEvents.map((item) => [item.id, { value: item.value, delta: item.change ?? 0 }])), [routeEvents])
  const exportFile = (fmt: 'csv' | 'xlsx') => {
    const monthStart = `2025-${String(month).padStart(2, '0')}-01`
    const monthEnd = `2025-${String(month).padStart(2, '0')}-${String(new Date(2025, month, 0).getDate()).padStart(2, '0')}`
    const q = new URLSearchParams({
      kind: 'forecast',
      format: fmt,
      granularity: mode === 'day' ? 'hour' : 'day',
      start: mode === 'month' ? monthStart : selectedDate,
      end: mode === 'day' ? selectedDate : mode === 'week' ? weekEnd : monthEnd,
    })
    if (route !== 'all') q.set('route', String(route))
    const link = document.createElement('a')
    link.href = `${API}/api/v1/export?${q}`
    link.click()
  }

  const navigateTo = (id: string, section: 'overview' | 'routes' | 'history') => {
    setNavSection(section)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    const dayCount = new Date(2025, month, 0).getDate()
    if (Number(selectedDate.slice(5, 7)) !== month) setSelectedDate(`2025-${String(month).padStart(2, '0')}-01`)
    else if (Number(selectedDate.slice(8, 10)) > dayCount) setSelectedDate(`2025-${String(month).padStart(2, '0')}-${String(dayCount).padStart(2, '0')}`)
  }, [month, selectedDate])

  useEffect(() => {
    if (mode === 'week' && selectedDate > WEEK_LAST_START) setSelectedDate(WEEK_LAST_START)
  }, [mode, selectedDate])

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if (event.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'SELECT') {
        event.preventDefault()
        searchRef.current?.focus()
      }
      if (event.key === 'Escape') {
        searchRef.current?.blur()
      }
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [])

  const selectedRoute = route === 'all' ? undefined : routeRanking.find((item) => item.id === route)
  const averageHour = dayTotal / 24
  const peakHourShare = dayTotal > 0 ? peak.passengers / dayTotal * 100 : 0
  const busyHours = hourlyDayRows.filter((row) => row.passengers >= peak.passengers * 0.8).length
  const selectedEvent = routeEvents.find((item) => item.id === selectedRoute?.id)
  const networkMonthTotal = monthForecast.reduce((sum, row) => sum + row.passengers, 0)
  const selectedRouteRank = selectedRoute ? routeRanking.findIndex((item) => item.id === selectedRoute.id) + 1 : 0
  const routeMonthShare = selectedRoute && networkMonthTotal > 0 ? selectedRoute.value / networkMonthTotal * 100 : 100
  const stopDayTotal = stopInsight?.hourly.reduce((sum, item) => sum + item.passengers, 0) ?? stopInsight?.boardings ?? 0
  const stopMonthTotal = stopInsight?.daily.reduce((sum, item) => sum + item.passengers, 0) ?? 0
  const stopWeekRows = stopInsight?.daily.filter((item) => item.date >= selectedDate && item.date <= weekEnd) ?? []
  const stopWeekTotal = stopWeekRows.reduce((sum, item) => sum + item.passengers, 0)
  const stopPeak = (stopInsight?.hourly ?? []).reduce((best, item) => item.passengers > best.passengers ? item : best, { hour: 0, passengers: 0 })
  const selectSearchResult = () => {
    const match = visibleEvents[0]
    if (match) {
      setRoute(match.id)
      setSearch('')
    }
  }
  const showRouteOnMap = () => {
    document.querySelector('.ops-grid .map-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  const selectStopOnMap = (stop: MapStop) => {
    setRoute(stop.route)
    setSelectedStop(stop)
    setDetailTab('stop')
  }
  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><img className="brand-logo" src={`${import.meta.env.BASE_URL}mostransport-logo.png`} alt="Московский транспорт" /><div><strong>МосТрам</strong><span>Прогноз пассажиропотока</span></div></div>
      <label className="global-search"><Search size={16} /><input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') selectSearchResult() }} aria-label="Поиск" placeholder="Поиск маршрута или остановки..." /><kbd>/</kbd><span>{search ? `${visibleEvents.length} найдено · Enter` : 'для быстрого поиска'}</span></label>
      <div className="period-tabs"><button className={mode === 'day' ? 'active' : ''} onClick={() => setMode('day')}>24 часа</button><button className={mode === 'week' ? 'active' : ''} onClick={() => setMode('week')}>Неделя</button><button className={mode === 'month' ? 'active' : ''} onClick={() => setMode('month')}>Месяц</button></div>
      <div className="top-actions"><div className="data-state"><span className={`live-dot ${error ? 'offline' : ''}`} /><div>Данные обновлены<b>{loading ? 'загружаем…' : 'только что'}</b></div></div></div>
    </header>
    <aside className="sidebar">
      <nav>
        <button className={`nav-item ${navSection === 'overview' ? 'active' : ''}`} onClick={() => navigateTo('overview', 'overview')}><Gauge size={18} /><span>Оперативный центр</span></button>
        <button className={`nav-item ${navSection === 'history' ? 'active' : ''}`} onClick={() => navigateTo('history', 'history')}><Activity size={18} /><span>Прогнозы</span></button>
        <button className="nav-item" onClick={() => exportFile('xlsx')}><Download size={18} /><span>Экспорт и отчёты</span></button>
        <a className="nav-item" href="#/tester"><FlaskConical size={18} /><span>Проверка API</span></a>
      </nav>
      <div className="side-bottom"><div className="system-card"><small>Статус системы</small><div className="system-row"><span className={`status-light ${health?.status === 'ok' ? '' : 'offline'}`} /> {health?.status === 'ok' ? 'В норме' : 'Проверка'}</div><dl><div><dt>API</dt><dd>{health?.version ?? '—'}</dd></div><div><dt>Маршрутов</dt><dd>{routes.length}</dd></div><div><dt>ML</dt><dd>активна</dd></div></dl></div><div className="city-sign"><img className="city-logo" src={`${import.meta.env.BASE_URL}mostransport-logo.png`} alt="Московский транспорт" /><span>Московский<br />метрополитен</span></div></div>
    </aside>
    <main className="main-content" id="overview">
      <section className="toolbar"><div className="toolbar-group"><span className="toolbar-caption">МЕСЯЦ</span><div className="month-switch"><button className={month === 11 ? 'selected' : ''} onClick={() => setMonth(11)}>Ноябрь</button><button className={month === 12 ? 'selected' : ''} onClick={() => setMonth(12)}>Декабрь</button></div></div><label className="select-wrap"><span className="toolbar-caption">МАРШРУТ</span><div className="select-control"><RouteIcon size={16} /><select value={route} onChange={(e) => setRoute(e.target.value === 'all' ? 'all' : Number(e.target.value))}><option value="all">Все маршруты</option>{routes.map((item) => <option key={item.id} value={item.id}>Трамвай {item.id}</option>)}</select><ChevronDown size={15} /></div></label><label className="select-wrap date-select"><span className="toolbar-caption">ДАТА</span><div className="select-control"><CalendarDays size={16} /><select value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}>{Array.from({ length: mode === 'week' && month === 12 ? 25 : new Date(2025, month, 0).getDate() }, (_, i) => { const d = `2025-${String(month).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`; return <option key={d} value={d}>{dateLabel(d, true)}</option> })}</select><ChevronDown size={15} /></div></label><button className="secondary-button" onClick={() => exportFile('xlsx')}><Download size={14} />Экспорт XLSX</button></section>
      <section className="control-strip"><div className="control-title"><b>События и приоритеты</b><span title="Показано маршрутов">{visibleEvents.length}/{routeEvents.length}</span></div><div className="map-modes"><button aria-pressed={mapMode === 'passengers'} title="Показывает каждый маршрут своим цветом" className={mapMode === 'passengers' ? 'active' : ''} onClick={() => setMapMode('passengers')}><Users size={15} />Пассажиропоток</button><button aria-pressed={mapMode === 'overload'} title="Окрашивает маршруты по уровню загрузки" className={mapMode === 'overload' ? 'active' : ''} onClick={() => setMapMode('overload')}><span className="red-ring" />Перегрузка</button><button aria-pressed={mapMode === 'deviation'} title="Показывает отклонение от исторического среднего" className={mapMode === 'deviation' ? 'active' : ''} onClick={() => setMapMode('deviation')}><Activity size={15} />Отклонение</button><button aria-pressed={mapMode === 'forecast'} title="Толщина линии отражает прогнозный пассажиропоток" className={mapMode === 'forecast' ? 'active' : ''} onClick={() => setMapMode('forecast')}><Sparkles size={15} />Прогноз</button></div><div className="route-title">{selectedStop ? `Остановка: ${selectedStop.name}` : selectedRoute ? `Детали маршрута ${selectedRoute.id}` : 'Сводка маршрутной сети'}</div></section>
      {error && <div className="error-banner">Не удалось загрузить данные: {error}. Убедитесь, что сервис доступен.</div>}
      {selectedRouteHasNoHistory && <div className="info-banner">По маршруту {route} нет исторических наблюдений.</div>}
      <section className="ops-grid">
        <article className="events-panel panel" id="routes"><div className="event-tabs"><button className={eventFilter === 'all' ? 'active' : ''} onClick={() => setEventFilter('all')}>Все маршруты <b>{routeEvents.length}</b></button><button className={eventFilter === 'critical' ? 'active' : ''} onClick={() => setEventFilter('critical')}>Критичные <b>{eventCounts.critical}</b></button><button className={eventFilter === 'warning' ? 'active' : ''} onClick={() => setEventFilter('warning')}>Риск <b>{eventCounts.warning}</b></button></div><label className="compact-select"><span>Сортировка:</span><select value={eventSort} onChange={(event) => setEventSort(event.target.value as typeof eventSort)}><option value="priority">По приоритету</option><option value="load">По пассажиропотоку</option><option value="route">По номеру маршрута</option></select><small>Показано {visibleEvents.length} из {routeEvents.length}</small></label><div className="ranking-list">{visibleEvents.map((item) => <button className={`event-card ${item.risk} ${route === item.id ? 'chosen' : ''}`} key={item.id} onClick={() => setRoute(route === item.id ? 'all' : item.id)}><TramFront size={18} /><span className="event-copy"><b>Маршрут {item.id}</b><strong>{item.risk === 'critical' ? 'Прогнозируется перегрузка' : item.risk === 'warning' ? 'Повышенная загрузка' : 'Штатная нагрузка'}</strong><small>{item.name}</small></span><span className="event-metric">{item.change === null ? '—' : `${item.change >= 0 ? '+' : ''}${item.change.toFixed(1)}%`}<i>{item.risk === 'critical' ? 'Критично' : item.risk === 'warning' ? 'Риск' : 'Норма'}</i></span></button>)}{visibleEvents.length === 0 && <div className="events-empty">Маршруты по заданным условиям не найдены</div>}</div><div className="events-scroll-hint">↕ Прокрутите список, чтобы увидеть все маршруты</div></article>
        <Suspense fallback={<div className="panel map-panel loading-card" />}><OverviewMap route={route} geo={geo} mode={mapMode} metrics={mapMetrics} stops={stops} selectedStop={selectedStop} onStopSelect={selectStopOnMap} /></Suspense>
        <article className="route-detail panel">
          <div className="detail-tabs"><button className={detailTab === 'overview' ? 'active' : ''} onClick={() => setDetailTab('overview')}>Обзор</button><button className={detailTab === 'load' ? 'active' : ''} onClick={() => setDetailTab('load')}>Нагрузка</button><button className={detailTab === 'forecast' ? 'active' : ''} onClick={() => setDetailTab('forecast')}>Прогноз</button>{selectedStop && <button className={detailTab === 'stop' ? 'active stop-tab' : 'stop-tab'} onClick={() => setDetailTab('stop')}><MapPinned size={12} />Остановка</button>}</div>
          <div className="route-head"><div className="route-symbol">{detailTab === 'stop' && selectedStop ? <MapPinned /> : <TramFront />}</div><div><h2>{detailTab === 'stop' && selectedStop ? selectedStop.name : selectedRoute ? `Маршрут ${selectedRoute.id}` : 'Все маршруты'}</h2><p>{detailTab === 'stop' && selectedStop ? `Маршрут ${selectedStop.route} · ${selectedStop.district ?? 'район не указан'}` : selectedRoute?.name ?? `${routes.length} маршрутов сети`}</p></div>{detailTab === 'stop' && selectedStop ? <button className="stop-clear" title="Закрыть сведения об остановке" onClick={() => { setSelectedStop(null); setDetailTab('overview') }}>×</button> : <span className={`critical-badge ${selectedEvent?.risk ?? 'info'}`}>{selectedEvent?.risk === 'critical' ? 'Критично' : selectedEvent?.risk === 'warning' ? 'Риск' : selectedRoute ? 'Норма' : 'Сеть'}</span>}</div>
          {detailTab === 'overview' && <div className="detail-tab-content"><div className="detail-kpis"><div><span>Прогноз на день</span><b>{format(dayTotal)}</b><small>посадок</small></div><div><span>К похожему дню</span><b>{delta >= 0 ? '+' : ''}{delta.toFixed(1)}%</b><small>{delta >= 0 ? 'рост' : 'снижение'}</small></div></div><h3>Положение в сети</h3><ul className="alerts">{selectedRoute ? <><li className="orange">Место по пассажиропотоку <b>№{selectedRouteRank}</b></li><li className="orange">Доля месячного потока сети <b>{routeMonthShare.toFixed(1)}%</b></li></> : <><li className={eventCounts.critical ? 'red' : 'orange'}>Критичных маршрутов <b>{eventCounts.critical}</b></li><li className="orange">Маршрутов в зоне риска <b>{eventCounts.warning}</b></li></>}</ul><div className="recommendation"><Sparkles size={18} /><div><b>Рекомендация системы</b><p>{delta > 10 ? 'Увеличить выпуск в пиковый интервал.' : 'Сохранить текущий выпуск и продолжить наблюдение.'}</p></div></div></div>}
          {detailTab === 'load' && <div className="detail-tab-content"><div className="detail-kpis"><div><span>Максимум за час</span><b>{format(peak.passengers)}</b><small>{String(peak.hour).padStart(2, '0')}:00–{String((peak.hour + 1) % 24).padStart(2, '0')}:00</small></div><div><span>Среднее за час</span><b>{format(averageHour)}</b><small>посадок</small></div></div><div className="load-summary"><div><span>Часов высокой нагрузки</span><b>{busyHours}</b></div><div><span>Доля потока в час пик</span><b>{peakHourShare.toFixed(1)}%</b></div></div><h3>Профиль нагрузки по часам</h3><div className="mini-bars">{hourlyDayRows.filter((row) => row.hour >= 6 && row.hour <= 22 && row.hour % 2 === 0).map((row) => <div key={row.hour}><span>{String(row.hour).padStart(2, '0')}</span><i><b style={{ height: `${Math.max(4, row.passengers / Math.max(peak.passengers, 1) * 100)}%` }} /></i></div>)}</div></div>}
          {detailTab === 'forecast' && <div className="detail-tab-content forecast-detail"><div className="detail-kpis"><div><span>На 7 дней</span><b>{format(weeklyTotal)}</b><small>{dateLabel(selectedDate)} — {dateLabel(weekEnd)}</small></div><div><span>На месяц</span><b>{format(allMonthTotal)}</b><small>{monthNames[month - 1].toLowerCase()} 2025</small></div></div><h3>Динамика на ближайшие 7 дней</h3><div className="mini-bars forecast-bars weekly-bars">{weeklyChart.map((row) => <div key={row.date}><span>{dateLabel(row.date)}</span><i><b style={{ height: `${Math.max(4, row.passengers / Math.max(...weeklyChart.map((item) => item.passengers), 1) * 100)}%` }} /></i></div>)}</div><div className="forecast-caption">Прогноз по дням без повторения почасовых показателей из вкладки «Нагрузка».</div></div>}
          {detailTab === 'stop' && selectedStop && <div className="detail-tab-content stop-detail">{stopInsightLoading ? <div className="detail-loading">Загружаем прогноз остановки…</div> : stopInsightError ? <div className="detail-error">{stopInsightError}</div> : stopInsight && <Suspense fallback={<div className="detail-loading">Строим график остановки…</div>}><StopHourly hourly={stopInsight.hourly} share={stopInsight.share} dateText={dateLabel(selectedDate)} weekTotal={stopWeekTotal} monthTotal={stopMonthTotal} format={format} /></Suspense>}</div>}
          <div className="detail-actions"><button className="active" onClick={showRouteOnMap}><MapPinned size={14} />Показать на карте</button><button onClick={() => exportFile('csv')}><Download size={14} />Скачать CSV</button></div>
        </article>
      </section>
      <section className="forecast-grid"><Suspense fallback={<div className="panel flow-panel loading-card" />}><FlowChart mode={mode} data={chartData} total={format(chartTotal)} caption={chartCaption} format={format} onModeChange={setMode} /></Suspense><article className="panel day-panel"><div className="panel-heading"><div><div className="panel-title">Почасовой прогноз</div><div className="panel-subtitle">{dateLabel(selectedDate, true)}</div></div><div className="date-chip">Таблица</div></div><div className="hour-table-head"><span>Время</span><span>Прогноз</span><span>Загрузка</span></div><div className="hour-list">{hourlyDayRows.filter((row) => row.hour >= 14 && row.hour <= 19).map((row) => { const pct = Math.round(row.passengers / Math.max(peak.passengers, 1) * 172); return <div className={`hour-row ${row.hour === peak.hour ? 'peak-row' : ''}`} key={row.hour}><span>{String(row.hour).padStart(2, '0')}:00</span><b>{format(row.passengers)}</b><strong className={pct > 130 ? 'hot' : ''}>{pct}%</strong></div> })}</div></article></section>
      <div className="deep-analytics"><div id="history"><Suspense fallback={<div className="loading-card">Загружаем прогнозные горизонты…</div>}><Horizons route={route} /></Suspense></div><div id="settings"><Suspense fallback={<div className="loading-card">Загружаем сценарии…</div>}><Coefficients route={route} /></Suspense></div></div>
      <footer className="page-footer"><span>Московский городской транспорт · Единый диспетчерский центр</span><span><span className="live-dot" /> модель временных рядов активна</span></footer>
    </main>
  </div>
}

export default App
