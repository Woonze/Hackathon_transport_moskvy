import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Activity, ArrowDownRight, FlaskConical, ArrowUpRight, CalendarDays, ChevronDown, Clock3, Route as RouteIcon, Sparkles, TramFront, Users, Zap } from 'lucide-react'
import type { FeatureCollection, LineString, MultiLineString } from 'geojson'
import './styles.css'

const Horizons = lazy(() => import('./panels/Horizons'))
const Coefficients = lazy(() => import('./panels/Coefficients'))
const Dispatch = lazy(() => import('./panels/Dispatch'))
const StopsMap = lazy(() => import('./panels/StopsMap'))
const OverviewMap = lazy(() => import('./panels/OverviewMap'))
const FlowChart = lazy(() => import('./panels/FlowChart'))

type Flow = { route: number; date: string; hour: number; passengers: number }
type TramRoute = { id: number; name: string; historical_total: number; forecast_total: number }
type WeekdayAverage = { route: number; weekday: number; passengers: number }
type Health = { status: 'ok' | 'error'; version: string }
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
  const [health, setHealth] = useState<Health | null>(null)
  const [month, setMonth] = useState(11)
  const [route, setRoute] = useState<number | 'all'>('all')
  const [navSection, setNavSection] = useState<'overview' | 'routes' | 'history'>('overview')
  const [selectedDate, setSelectedDate] = useState('2025-11-01')
  const [mode, setMode] = useState<'days' | 'hours'>('days')
  const [loading, setLoading] = useState(true)
  const [referenceError, setReferenceError] = useState('')
  const [forecastError, setForecastError] = useState('')
  const error = referenceError || forecastError
  const selectedRouteHasNoHistory = route !== 'all' && routes.find((item) => item.id === route)?.historical_total === 0

  useEffect(() => {
    const controller = new AbortController()
    setReferenceError('')
    Promise.all([
      fetch(`${API}/api/history/weekday-average`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Сводка истории недоступна'); return r.json() }),
      fetch(`${API}/api/routes`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Маршруты недоступны'); return r.json() }),
      fetch(`${API}/api/map`, { signal: controller.signal }).then((r) => r.ok ? r.json() : { type: 'FeatureCollection', features: [] }),
      fetch(`${API}/api/health`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Сервис недоступен'); return r.json() }),
    ]).then(([hist, routeList, routeGeo, serviceHealth]) => {
      setWeekdayAverages(hist); setRoutes(routeList); setGeo(routeGeo); setHealth(serviceHealth)
    }).catch((e: Error) => { if (e.name !== 'AbortError') setReferenceError(e.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setForecastError('')
    const start = `2025-${String(month).padStart(2, '0')}-01`
    const end = `2025-${String(month).padStart(2, '0')}-${String(new Date(2025, month, 0).getDate()).padStart(2, '0')}`
    setLoading(true)
    Promise.all([
      fetch(`${API}/api/forecast?start=${start}&end=${end}&granularity=day`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Прогноз недоступен'); return r.json() }),
      fetch(`${API}/api/forecast?start=${selectedDate}&end=${selectedDate}&granularity=hour`, { signal: controller.signal }).then((r) => { if (!r.ok) throw new Error('Почасовой прогноз недоступен'); return r.json() }),
    ]).then(([monthRows, dateRows]) => {
      setForecast(monthRows.map((row: Omit<Flow, 'hour'>) => ({ ...row, hour: 0 })))
      setDateForecast(dateRows)
      setLoading(false)
    }).catch((e: Error) => { if (e.name !== 'AbortError') { setForecastError(e.message); setLoading(false) } })
    return () => controller.abort()
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
  const exportFile = (fmt: 'csv' | 'xlsx') => {
    const q = new URLSearchParams({ kind: 'forecast', format: fmt, granularity: mode === 'days' ? 'day' : 'hour', start: `2025-${String(month).padStart(2, '0')}-01`, end: `2025-${String(month).padStart(2, '0')}-${String(new Date(2025, month, 0).getDate()).padStart(2, '0')}` })
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

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><TramFront size={21} strokeWidth={2.2} /></div><div><strong>МОС.ТРАМ</strong><span>АНАЛИТИКА ПОТОКА</span></div></div>
      <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <button aria-label="Обзор пассажиропотока" title="Обзор пассажиропотока" className={`nav-item ${navSection === 'overview' ? 'active' : ''}`} onClick={() => navigateTo('overview', 'overview')}><Activity size={18} /><span>Обзор пассажиропотока</span>{navSection === 'overview' && <span className="active-dot" />}</button>
      <button aria-label="Маршруты" title="Маршруты" className={`nav-item ${navSection === 'routes' ? 'active' : ''}`} onClick={() => navigateTo('routes', 'routes')}><RouteIcon size={18} /><span>Маршруты</span><span className="nav-soon">10</span></button>
      <button aria-label="История данных" title="История данных" className={`nav-item ${navSection === 'history' ? 'active' : ''}`} onClick={() => navigateTo('history', 'history')}><CalendarDays size={18} /><span>История данных</span></button>
      <a className="nav-item" href="#/tester" aria-label="Проверка API" title="Проверка API" style={{ textDecoration: 'none', color: 'inherit' }}><FlaskConical size={18} /><span>Проверка API</span></a>
      <div className="side-bottom"><div className="system-card"><div className="system-row"><span className={`status-light ${health?.status === 'ok' ? '' : 'offline'}`} /> {health?.status === 'ok' ? 'Сервис доступен' : 'Проверяем сервис'}</div><p>Горизонт прогноза<br />01 ноя — 31 дек 2025</p><div className="system-foot"><span>API {health?.version ?? '—'}</span><span className="spark"><Sparkles size={13} /> ML</span></div></div><div className="user-row"><div className="avatar">ЕД</div><div><strong>Диспетчер ЕДЦ</strong><span>Москва · Трамвай</span></div></div></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="crumbs">Аналитика <span>/</span> <b>Пассажиропоток</b></div><div className="top-actions"><div className="live-pill"><span className={`live-dot ${error ? 'offline' : ''}`} /> {error ? 'Ошибка загрузки' : loading ? 'Загрузка прогноза' : 'Прогноз готов'}</div><a className="icon-button" title="Открыть справку API" href="/docs" target="_blank" rel="noreferrer"><span>?</span></a><div className="top-avatar">ЕД</div></div></header>
      <div className="content-wrap">
        <section className="page-heading" id="overview"><div><div className="eyebrow"><span className="eyebrow-line" /> ПЛАНИРОВАНИЕ · НОЯБРЬ—ДЕКАБРЬ 2025</div><h1>Пассажиропоток трамваев</h1><p>Прогноз загрузки маршрутов по часам и дням для оперативного планирования</p></div><div className="heading-actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button className="secondary-button" onClick={() => exportFile('csv')} title="Прогноз выбранного месяца и маршрута с текущей детализацией"><span className="export-icon">↧</span> CSV</button><button className="secondary-button" onClick={() => exportFile('xlsx')} title="Прогноз выбранного месяца и маршрута с листом «Сводка»"><span className="export-icon">↧</span> XLSX</button></div></section>
        <section className="toolbar"><div className="toolbar-group"><div className="toolbar-caption">ПЕРИОД ПРОГНОЗА</div><div className="month-switch"><button className={month === 11 ? 'selected' : ''} onClick={() => setMonth(11)}>Ноябрь</button><button className={month === 12 ? 'selected' : ''} onClick={() => setMonth(12)}>Декабрь</button></div></div><div className="toolbar-separator" /><label className="select-wrap"><span className="toolbar-caption">МАРШРУТ</span><div className="select-control"><RouteIcon size={16} /><select value={route} onChange={(e) => setRoute(e.target.value === 'all' ? 'all' : Number(e.target.value))}><option value="all">Все маршруты</option>{routes.map((item) => <option key={item.id} value={item.id}>Трамвай {item.id}</option>)}</select><ChevronDown size={15} /></div></label><div className="toolbar-separator" /><label className="select-wrap date-select"><span className="toolbar-caption">ДАТА ДЛЯ ДЕТАЛЬНОГО ПРОСМОТРА</span><div className="select-control"><CalendarDays size={16} /><select value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}>{Array.from({ length: new Date(2025, month, 0).getDate() }, (_, i) => { const d = `2025-${String(month).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`; return <option key={d} value={d}>{dateLabel(d, true)}</option> })}</select><ChevronDown size={15} /></div></label><div className="updated-label"><span className={`live-dot ${health?.status === 'ok' ? '' : 'offline'}`} /> Статус API<br /><b>{health ? `Версия ${health.version}` : 'Проверка…'}</b></div></section>

        {error && <div className="error-banner">Не удалось загрузить данные: {error}. Убедитесь, что сервис доступен.</div>}
        {selectedRouteHasNoHistory && <div className="info-banner" role="status">По маршруту {route} в исходных данных нет исторических наблюдений. Нулевые значения прогноза сохранены как в шаблоне организаторов и не означают подтверждённое отсутствие пассажиров.</div>}
        {loading && <div className="loading-card"><div className="loader" /> Загружаем прогноз и справочники…</div>}

        <section className="kpi-grid">
          <article className="kpi-card primary-kpi"><div className="kpi-top"><div className="kpi-icon blue"><Users size={18} /></div><span className="kpi-tag"><Sparkles size={12} /> ПРОГНОЗ</span></div><div className="kpi-label">Посадки за выбранный день</div><div className="kpi-value">{format(dayTotal)} <small>пасс.</small></div><div className="kpi-foot"><span className={delta >= 0 ? 'trend positive' : 'trend negative'}>{delta >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}{Math.abs(delta).toFixed(1)}%</span><span>к среднему за похожий день</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon purple"><Clock3 size={18} /></div><span className="kpi-tag muted">ПИКОВАЯ НАГРУЗКА</span></div><div className="kpi-label">Час максимального потока</div><div className="kpi-value">{String(peak.hour).padStart(2, '0')}:00 <small>— {String((peak.hour + 1) % 24).padStart(2, '0')}:00</small></div><div className="kpi-foot"><span className="foot-dot purple-dot" /> <b>{format(peak.passengers)}</b><span>посадок за час</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon mint"><CalendarDays size={18} /></div><span className="kpi-tag muted">{monthNames[month - 1].toUpperCase()} 2025</span></div><div className="kpi-label">Прогноз за месяц</div><div className="kpi-value">{format(allMonthTotal)} <small>пасс.</small></div><div className="kpi-foot"><span className="foot-dot green-dot" /> <b>{dailyChart.length}</b><span>дней в расчёте</span></div></article>
          <article className="kpi-card"><div className="kpi-top"><div className="kpi-icon orange"><Zap size={18} /></div><span className="kpi-tag muted">ГОРИЗОНТ</span></div><div className="kpi-label">Детализация прогноза</div><div className="kpi-value">24 <small>часа</small></div><div className="kpi-foot"><span className="foot-dot orange-dot" /> <b>10</b><span>трамвайных маршрутов</span></div></article>
        </section>

        <section className="main-grid">
          <Suspense fallback={<div className="panel map-panel loading-card" />}><OverviewMap route={route} geo={geo} /></Suspense>
          <Suspense fallback={<div className="panel flow-panel loading-card" />}><FlowChart mode={mode} data={mode === 'days' ? dailyChart : hourlyChart} total={format(mode === 'days' ? allMonthTotal : dayTotal)} caption={mode === 'days' ? 'посадок за месяц' : `посадок · ${dateLabel(selectedDate)}`} format={format} onModeChange={setMode} /></Suspense>
        </section>

        <section className="bottom-grid"><article className="panel ranking-panel" id="routes"><div className="panel-heading"><div><div className="panel-title">Загрузка маршрутов</div><div className="panel-subtitle">Прогноз посадок · {monthNames[month - 1].toLowerCase()} 2025</div></div><button className="text-action" onClick={() => setRoute('all')}>Все маршруты <span>→</span></button></div><div className="ranking-list">{routeRanking.map((item, index) => <button className={`ranking-row ${route === item.id ? 'chosen' : ''}`} key={item.id} onClick={() => setRoute(route === item.id ? 'all' : item.id)}><span className="rank-num">{String(index + 1).padStart(2, '0')}</span><span className="route-number" style={{ color: routeColors[item.id], background: `${routeColors[item.id]}13` }}>{item.id}</span><span className="rank-bar-track"><span className="rank-bar-fill" style={{ width: `${routeRanking[0]?.value ? item.value / routeRanking[0].value * 100 : 0}%`, background: routeColors[item.id] }} /></span><span className="rank-value">{item.historical_total === 0 ? '—' : format(item.value)}</span><span className="rank-label">{item.historical_total === 0 ? 'нет истории' : 'посадок'}</span></button>)}</div><div className="ranking-footer">Выберите маршрут, чтобы отфильтровать карту и прогноз</div></article><article className="panel day-panel"><div className="panel-heading"><div><div className="panel-title">Почасовой прогноз</div><div className="panel-subtitle">{dateLabel(selectedDate, true)}</div></div><div className="date-chip"><CalendarDays size={14} /> {monthNames[month - 1]}</div></div><div className="hour-list">{hourlyDayRows.filter((row) => row.hour >= 5 && row.hour <= 23).map((row) => { const max = Math.max(...hourlyDayRows.map((r) => r.passengers), 1); return <div className={`hour-row ${row.hour === peak.hour ? 'peak-row' : ''}`} key={row.hour}><span className="hour-time">{String(row.hour).padStart(2, '0')}:00</span><span className="hour-bar-bg"><span className="hour-bar" style={{ width: `${row.passengers / max * 100}%` }} /></span><span className="hour-value">{format(row.passengers)}</span>{row.hour === peak.hour && <span className="peak-label">ПИК</span>}</div> })}</div><div className="day-total"><span>Итого за день</span><strong>{format(dayTotal)} <small>посадок</small></strong></div></article></section>
        <Suspense fallback={<div className="loading-card">Загружаем аналитику остановок…</div>}><StopsMap route={route} routeSummaries={routes} /></Suspense>
        <Suspense fallback={<div className="loading-card">Загружаем сводку диспетчера…</div>}><Dispatch route={route} /></Suspense>
        <div id="history"><Suspense fallback={<div className="loading-card">Загружаем прогнозные горизонты…</div>}><Horizons route={route} /></Suspense></div>
        <Suspense fallback={<div className="loading-card">Загружаем сценарии…</div>}><Coefficients route={route} /></Suspense>
        <footer className="page-footer"><span>Московский городской транспорт <b>·</b> Единый диспетчерский центр</span><span><span className="live-dot" /> Данные прогноза · модель временных рядов</span></footer>
      </div>
    </main>
  </div>
}

export default App
