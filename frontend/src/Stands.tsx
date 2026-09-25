import { useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, CalendarDays, Check,
  ChevronDown, CircleHelp, Clock3, CloudRain, Download, Gauge, Layers3, MapPin,
  Route, Search, Settings2, ShieldCheck, Sparkles, TramFront, Users, Zap,
} from 'lucide-react'
import './stands.css'
import './stands-map.css'
import OverviewMap from './panels/OverviewMap'

type StandsGeo = {
  type: 'FeatureCollection'
  features: { type: 'Feature'; geometry: { type: 'LineString' | 'MultiLineString'; coordinates: number[][] | number[][][] }; properties: { route: number; stop_count: number; stops: string[] } }[]
}

type Horizon = 'day' | 'week' | 'month'
type StandId = 'overview' | 'routes' | 'heatmap' | 'scenario' | 'dispatch'

const stands: { id: StandId; number: string; title: string; detail: string }[] = [
  { id: 'overview', number: '01', title: 'Оперативный обзор', detail: 'Все важное на одном экране' },
  { id: 'routes', number: '02', title: 'Маршрутный радар', detail: 'Сравнение маршрутов' },
  { id: 'heatmap', number: '03', title: 'Карта спроса', detail: 'Часы и дни недели' },
  { id: 'scenario', number: '04', title: 'Сценарии', detail: 'Что изменится при факторах' },
  { id: 'dispatch', number: '05', title: 'Диспетчерский центр', detail: 'Пики и отклонения' },
]

const routeData = [
  { id: 17, name: 'Медведково — Останкино', total: 1482521, delta: 8.4, peak: '08:00', load: 92, color: '#71a7ff' },
  { id: 12, name: 'Бульвар Рокоссовского — 3-я Владимирская', total: 974977, delta: 3.1, peak: '18:00', load: 81, color: '#b79aff' },
  { id: 11, name: 'Останкино — Белорусский вокзал', total: 939021, delta: -2.6, peak: '08:00', load: 77, color: '#56d8bb' },
  { id: 7, name: 'Метро «Университет» — Новые Черёмушки', total: 677000, delta: 5.7, peak: '17:00', load: 68, color: '#ffbd71' },
  { id: 50, name: 'Метро «Ботанический сад» — Тихвинская', total: 620576, delta: 1.9, peak: '09:00', load: 61, color: '#f48caa' },
  { id: 1, name: 'Чертановская — Москворецкий рынок', total: 482521, delta: -1.3, peak: '08:00', load: 54, color: '#72c3ee' },
]

const hourProfile = [18, 12, 9, 8, 11, 24, 48, 74, 89, 82, 68, 63, 67, 76, 84, 90, 87, 74, 56, 43, 35, 29, 22, 14]
const weekdayLabels = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
const hourLabels = ['00', '03', '06', '09', '12', '15', '18', '21']
const fmt = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))

function SmallLine({ seed, color = 'currentColor' }: { seed: number; color?: string }) {
  const points = Array.from({ length: 18 }, (_, i) => {
    const y = 18 - (((Math.sin((i + seed) * 1.21) + 1) * 0.25 + (Math.cos((i + seed) * 0.59) + 1) * 0.18 + i / 18 * 0.22) * 18)
    return `${i * 5},${Math.max(1, Math.min(19, y)).toFixed(1)}`
  }).join(' ')
  return <svg className="stand-sparkline" viewBox="0 0 86 22" preserveAspectRatio="none" aria-hidden="true"><polyline points={points} fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

function StandsMap({ route }: { route: number | 'all' }) {
  const [geo, setGeo] = useState<StandsGeo>({ type: 'FeatureCollection', features: [] })
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/map', { signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then((data) => { if (data?.features) setGeo(data as StandsGeo) })
      .catch(() => {})
    return () => controller.abort()
  }, [])
  const routeGeometryAvailable = route === 'all' || geo.features.some((feature) => feature.properties.route === route)
  return <div className="stands-map-slot">
    {!routeGeometryAvailable && <div className="stands-map-hint">Для маршрута №{route} геометрия пока не загружена — показана доступная сеть.</div>}
    <OverviewMap route={routeGeometryAvailable ? route : 'all'} geo={geo as never} />
  </div>
}

function Trend({ value }: { value: number }) {
  return <span className={`stand-trend ${value >= 0 ? 'up' : 'down'}`}>{value >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{Math.abs(value).toFixed(1)}%</span>
}

function FlowChart({ horizon, route, startDate }: { horizon: Horizon; route: number | 'all'; startDate: Date }) {
  const count = horizon === 'day' ? 24 : horizon === 'week' ? 7 : 30
  const values = Array.from({ length: count }, (_, i) => {
    if (horizon === 'day') return hourProfile[i] * (route === 'all' ? 1300 : route === 17 ? 340 : 210) * (1 + Math.sin(i * 0.83) * 0.09)
    const trend = horizon === 'week' ? 1 + i * 0.013 : 1 + Math.sin(i / 4.4) * 0.14
    return (route === 'all' ? 168000 : route === 17 ? 41400 : 25500) * trend * (i % 7 === 5 || i % 7 === 6 ? 0.77 : 1)
  })
  const max = Math.max(...values) * 1.14
  const width = 740
  const height = 210
  const points = values.map((value, i) => `${(i / Math.max(1, count - 1) * width).toFixed(1)},${(height - value / max * height).toFixed(1)}`)
  const line = points.join(' ')
  const area = `0,${height} ${line} ${width},${height}`
  const ticks = horizon === 'day'
    ? ['00', '04', '08', '12', '16', '20', '24']
    : Array.from({ length: 7 }, (_, i) => {
      const date = horizon === 'week' ? new Date(startDate) : new Date(startDate.getFullYear(), startDate.getMonth(), 1 + Math.round(i * 29 / 6))
      if (horizon === 'week') date.setDate(date.getDate() + i)
      return horizon === 'week' ? new Intl.DateTimeFormat('ru-RU', { weekday: 'short' }).format(date).slice(0, 2).toUpperCase() : new Intl.DateTimeFormat('ru-RU', { day: '2-digit' }).format(date)
    })
  return <div className="stand-chart"><div className="chart-y-labels"><span>{fmt(max)}</span><span>{fmt(max * .66)}</span><span>{fmt(max * .33)}</span><span>0</span></div><div className="chart-canvas"><svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Динамика прогноза пассажиропотока"><defs><linearGradient id="stand-chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7397ff" stopOpacity=".28" /><stop offset="1" stopColor="#7397ff" stopOpacity="0" /></linearGradient></defs><path d={`M ${area} Z`} fill="url(#stand-chart-fill)" /><polyline points={line} fill="none" stroke="#86a4ff" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />{points.filter((_, i) => i === Math.floor(count * .34) || i === Math.floor(count * .72)).map((point) => { const [cx, cy] = point.split(','); return <circle key={point} cx={cx} cy={cy} r="4" fill="#c3d1ff" stroke="#161c29" strokeWidth="2" vectorEffect="non-scaling-stroke" /> })}</svg><div className="chart-grid"><i /><i /><i /><i /></div><div className="chart-x-labels">{ticks.map((tick) => <span key={tick}>{tick}</span>)}</div></div></div>
}

function MetricCard({ icon, label, value, note, trend, color, seed }: { icon: React.ReactNode; label: string; value: string; note: string; trend?: number; color: string; seed: number }) {
  return <article className="stand-metric"><div className="stand-metric-top"><span className={`stand-metric-icon ${color}`}>{icon}</span>{trend !== undefined && <Trend value={trend} />}</div><span className="stand-metric-label">{label.replace(/»/g, '')}</span><strong className="stand-metric-value">{value.replace(/»/g, '')}</strong><div className="stand-metric-bottom"><span>{note.replace(/»/g, '')}</span><SmallLine seed={seed} color="var(--accent)" /></div></article>
}

function HourHeatmap() {
  return <div className="heatmap-wrap"><div className="heatmap-hours"><span />{hourLabels.map((hour) => <span key={hour}>{hour}:00</span>)}</div>{weekdayLabels.map((day, dayIndex) => <div className="heatmap-row" key={day}><b>{day}</b>{Array.from({ length: 8 }, (_, hourIndex) => {
    const value = hourProfile[Math.min(hourIndex * 3 + 1, 23)] * (dayIndex > 4 ? .68 : dayIndex === 0 ? .92 : 1) * (1 + Math.sin(dayIndex * 1.7 + hourIndex) * .08)
    return <div key={hourIndex} className="heat-cell" style={{ backgroundColor: `rgba(98, 210, 185, ${Math.min(value / 100, 1)})` }} title={`${day}, ${hourLabels[hourIndex]}:00 · нагрузка ${Math.round(value)}%`} role="img" aria-label={`${day}, ${hourLabels[hourIndex]}:00, нагрузка ${Math.round(value)} процентов`} />
  })}</div>)}</div>
}

function Stands() {
  const [active, setActive] = useState<StandId>('overview')
  const [horizon, setHorizon] = useState<Horizon>('week')
  const [route, setRoute] = useState<number | 'all'>('all')
  const [weather, setWeather] = useState(1)
  const [event, setEvent] = useState(1)
  const [season, setSeason] = useState(1)
  const [dateStart, setDateStart] = useState('2025-11-03')
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const selectedDate = new Date(`${dateStart}T12:00:00`)
  const isDecember = selectedDate.getMonth() === 11
  const periodScale = horizon === 'month' ? 1 : horizon === 'week' ? 1 / 4.2 : 1 / 30
  const visibleRoutes = useMemo(() => routeData
    .filter((item) => (route === 'all' || item.id === route) && `${item.id} ${item.name}`.toLowerCase().includes(query.toLowerCase()))
    .map((item) => ({ ...item, total: Math.round(item.total * (isDecember ? 1.07 : 1) * periodScale) })), [route, query, isDecember, periodScale])
  const factor = weather * event * season
  const baseTotal = route === 'all' ? horizon === 'month' ? isDecember ? 6696474 : 6236738 : horizon === 'week' ? 1490127 : 148495 : (routeData.find((item) => item.id === route)?.total ?? 482521) * (isDecember ? 1.07 : 1) * periodScale
  const currentTotal = baseTotal * factor
  const currentStand = stands.find((item) => item.id === active)!
  const rangeStart = horizon === 'month' ? new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1) : selectedDate
  const rangeEnd = horizon === 'month'
    ? new Date(selectedDate.getFullYear(), selectedDate.getMonth() + 1, 0)
    : new Date(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate() + (horizon === 'week' ? 6 : 0))
  const dateLabel = (date: Date) => new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(date).replace(' г.', '')

  const exportMock = () => {
    const header = 'route;start;end;granularity;forecast;source\n'
    const start = `${rangeStart.getFullYear()}-${String(rangeStart.getMonth() + 1).padStart(2, '0')}-${String(rangeStart.getDate()).padStart(2, '0')}`
    const end = `${rangeEnd.getFullYear()}-${String(rangeEnd.getMonth() + 1).padStart(2, '0')}-${String(rangeEnd.getDate()).padStart(2, '0')}`
    const granularity = horizon === 'day' ? 'hour' : 'day'
    const rows = visibleRoutes.map((item) => `${item.id};${start};${end};${granularity};${Math.round(item.total * factor)};mock`).join('\n')
    const url = URL.createObjectURL(new Blob([header + rows], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'mos-tram-ux-mock.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return <div className="stands-shell">
    <aside className="stands-sidebar">
      <a href="#/" className="stands-brand"><span className="stands-brand-mark"><TramFront size={19} /></span><span><b>МОС.ТРАМ</b><small>OPERATIONS · UX LAB</small></span></a>
      <div className="stands-side-label">КОНЦЕПЦИИ · 5 ВАРИАНТОВ</div>
      <nav className="stands-nav" aria-label="Варианты интерфейса">{stands.map((item) => <button key={item.id} className={`stands-nav-item ${active === item.id ? 'selected' : ''}`} onClick={() => setActive(item.id)}><span className="stands-nav-num">{item.number}</span><span className="stands-nav-copy"><b>{item.title}</b><small>{item.detail}</small></span>{active === item.id && <span className="stands-nav-mark" />}</button>)}</nav>
      <div className="stands-sidebar-bottom"><div className="stands-live"><span /> Демо-среда активна</div><a href="#/" className="stands-back">← К основному дашборду</a></div>
    </aside>

    <main className="stands-main">
      <header className="stands-topbar"><div className="stands-breadcrumb">Операционный центр <span>/</span> <b>{currentStand.title}</b></div><div className="stands-top-actions"><span className="stands-demo-badge"><span /> MOCK DATA</span><button className="stands-icon-button" aria-label="Справка" title="Справка"><CircleHelp size={16} /></button><button className="stands-icon-button" aria-label="Уведомления" title="Уведомления"><Bell size={16} /><i /></button><span className="stands-user">ЕД</span></div></header>
      <div className="stands-content">
        <section className="stands-heading"><div><div className="stands-eyebrow"><span /> МОСКВА · ТРАМВАЙ · 2025</div><h1>{currentStand.title}</h1><p>{currentStand.detail} · прогноз на ноябрь—декабрь</p></div><button className="stands-export" onClick={exportMock}><Download size={15} /> Экспорт</button></section>

        <section className="stands-filterbar" aria-label="Общие фильтры дашборда"><div className="stands-filter-item"><span>ГОРИЗОНТ</span><div className="stands-toggle" role="group" aria-label="Горизонт прогноза">{(['day', 'week', 'month'] as Horizon[]).map((item) => <button key={item} aria-pressed={horizon === item} className={horizon === item ? 'active' : ''} onClick={() => setHorizon(item)}>{item === 'day' ? 'Сутки' : item === 'week' ? 'Неделя' : 'Месяц'}</button>)}</div></div><div className="stands-filter-divider" /><label className="stands-filter-item route-filter"><span>МАРШРУТ</span><div className="stands-select"><Route size={15} /><select value={route} onChange={(e) => setRoute(e.target.value === 'all' ? 'all' : Number(e.target.value))}><option value="all">Все маршруты</option>{routeData.map((item) => <option value={item.id} key={item.id}>№ {item.id} · {item.name.split(' — ')[0]}</option>)}</select><ChevronDown size={14} /></div></label><div className="stands-filter-divider" /><label className="stands-filter-item"><span>ПЕРИОД · {horizon === 'week' ? 'НАЧАЛО НЕДЕЛИ' : 'ДАТА'}</span><div className="stands-date-control"><CalendarDays size={15} /><select value={dateStart} onChange={(e) => setDateStart(e.target.value)} aria-label="Начало периода"><option value="2025-11-03">3 ноября 2025</option><option value="2025-11-28">28 ноября 2025</option><option value="2025-12-01">1 декабря 2025</option><option value="2025-12-25">25 декабря 2025</option></select><ChevronDown size={14} /></div></label><span className="stands-range-label">{dateLabel(rangeStart)} — {dateLabel(rangeEnd)}</span><span className="stands-last-update"><span className="update-dot" /> Обновлено сейчас</span></section>

        {notice && <div className="stands-toast" role="status"><Check size={15} />{notice}<button onClick={() => setNotice('')} aria-label="Закрыть">×</button></div>}

        {active === 'routes' && <StandsMap route={route} />}

        {active === 'overview' && <>
          <section className="stands-metrics four-metrics"><MetricCard icon={<Users size={17} />} label="Прогноз пассажиров" value={fmt(currentTotal)} note={horizon === 'day' ? 'за выбранные сутки' : horizon === 'week' ? 'за 7 дней' : `за ${new Intl.DateTimeFormat('ru-RU', { month: 'long' }).format(selectedDate)}`} trend={6.8} color="blue" seed={3} /><MetricCard icon={<Gauge size={17} />} label="Средняя загрузка" value={route === 'all' ? '74%' : `${routeData.find((x) => x.id === route)?.load ?? 62}%`} note="от доступной вместимости" trend={2.1} color="violet" seed={6} /><MetricCard icon={<Clock3 size={17} />} label="Час пик" value="08:00–09:00" note="утренний максимум" color="amber" seed={8} /><MetricCard icon={<ShieldCheck size={17} />} label="Точность модели" value="88,4%" note="WAPE · бэктест Sep–Oct" trend={1.4} color="mint" seed={11} /></section>
          <section className="stands-main-grid"><article className="stands-card stands-flow-card"><div className="stands-card-head"><div><h2>Пассажиропоток</h2><p>{horizon === 'day' ? 'Интервал 1 час' : horizon === 'week' ? 'Интервал 1 день · 7 дней' : `Интервал 1 день · ${new Intl.DateTimeFormat('ru-RU', { month: 'long' }).format(selectedDate)}`}</p></div><div className="stands-chart-legend"><span /> Прогноз <button title="Настройки графика" aria-label="Настройки графика"><Settings2 size={15} /></button></div></div><div className="stands-chart-total"><strong>{fmt(currentTotal)}</strong><span>пассажиров за период</span><Trend value={6.8} /></div><FlowChart horizon={horizon} route={route} startDate={rangeStart} /><div className="stands-chart-foot"><span><i /> Прогноз модели</span><span><i className="dashed" /> Факт · для сравнения</span><button onClick={() => { setActive('heatmap'); setNotice('Открыта детализация спроса по дням недели и часам') }}>Открыть профиль <ArrowRight size={14} /></button></div></article>
            <article className="stands-card stands-insight-card"><div className="stands-card-head"><div><h2>Сейчас важно</h2><p>Автоматические сигналы модели</p></div><span className="stands-count-badge">3</span></div><div className="stands-insight-list"><button onClick={() => { setActive('dispatch'); setNotice('Показаны маршруты с максимальной нагрузкой') }}><span className="insight-icon hot"><Zap size={15} /></span><span><b>Пиковая нагрузка через 35 минут</b><small>Маршрут №17 · 92% вместимости</small></span><ArrowRight size={15} /></button><button onClick={() => { setActive('routes'); setRoute(11) }}><span className="insight-icon calm"><Activity size={15} /></span><span><b>Поток ниже обычного</b><small>Маршрут №11 · −2,6% к типичному дню</small></span><ArrowRight size={15} /></button><button onClick={() => { setActive('scenario'); setNotice('Открыты факторы влияния на прогноз') }}><span className="insight-icon rain"><CloudRain size={15} /></span><span><b>Ожидается снегопад</b><small>Сценарная поправка может изменить спрос</small></span><ArrowRight size={15} /></button></div><button className="stands-all-signals" onClick={() => setActive('dispatch')}>Все сигналы <ArrowRight size={14} /></button></article></section>
          <RouteTable routes={visibleRoutes.slice(0, 5)} onChoose={(id) => { setRoute(id); setActive('routes') }} onOpenAll={() => setActive('routes')} />
        </>}

        {active === 'routes' && <><section className="stands-metrics three-metrics"><MetricCard icon={<Route size={17} />} label="Активные маршруты" value={route === 'all' ? '10' : '1'} note="в выбранном срезе" color="blue" seed={2} /><MetricCard icon={<Users size={17} />} label="Суммарный спрос" value={fmt(currentTotal)} note="прогноз за период" trend={4.6} color="violet" seed={4} /><MetricCard icon={<Zap size={17} />} label="Нагрузка выше 85%" value={visibleRoutes.filter((x) => x.load > 85).length.toString()} note="маршрута требуют внимания" color="amber" seed={9} /></section><article className="stands-card stands-table-card"><div className="stands-card-head"><div><h2>Маршруты · сравнение показателей</h2><p>Выберите строку, чтобы применить маршрут ко всему экрану</p></div><label className="stands-search"><Search size={15} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Номер или название" /></label></div><RouteTable routes={visibleRoutes} onChoose={(id) => { setRoute(id); setNotice(`Выбран маршрут №${id}; показатели пересчитаны`) }} expanded /></article><section className="stands-bottom-grid"><InsightMini icon={<MapPin size={16} />} title="Маршрут с самой высокой загрузкой" value="№17 · 92%" caption="Пик сегодня в 08:00–09:00" /><InsightMini icon={<Activity size={16} />} title="Наибольший рост к прошлой неделе" value="№17 · +8,4%" caption="1,48 млн посадок за месяц" /></section></>}

        {active === 'heatmap' && <><section className="stands-metrics three-metrics"><MetricCard icon={<Clock3 size={17} />} label="Пиковый интервал»" value="08:00–09:00" note="будни · утро" color="amber" seed={1} /><MetricCard icon={<CalendarDays size={17} />} label="Самый загруженный день»" value="Пятница" note="в среднем +12% к неделе" trend={12} color="blue" seed={5} /><MetricCard icon={<Users size={17} />} label="Пассажиров в пик»" value={fmt(baseTotal * .092)} note="оценка по выбранному маршруту" color="violet" seed={10} /></section><section className="stands-main-grid heat-layout"><article className="stands-card heat-card"><div className="stands-card-head"><div><h2>Нагрузка по дням и времени</h2><p>Цвет показывает прогнозную загрузку относительно среднего значения</p></div><button className="stands-quiet-button"><Layers3 size={14} /> По загрузке <ChevronDown size={13} /></button></div><HourHeatmap /><div className="heat-legend"><span>Ниже среднего</span><div>{['#202c3c', '#2c435d', '#365d7b', '#468a9b', '#61c8b1'].map((color) => <i key={color} style={{ background: color }} />)}</div><span>Выше среднего</span></div></article><article className="stands-card profile-card"><div className="stands-card-head"><div><h2>Профиль дня</h2><p>Все маршруты · типичный будний день</p></div></div><div className="profile-bars">{hourProfile.map((value, i) => <div className="profile-bar-item" key={i} title={`${String(i).padStart(2, '0')}:00 · ${value}%`}><i style={{ height: `${value}%` }} className={value >= 80 ? 'peak' : ''} /><span>{i % 4 === 0 ? `${String(i).padStart(2, '0')}` : ''}</span></div>)}</div><div className="profile-caption"><span>00:00</span><span>Утренний пик</span><span>23:00</span></div><div className="profile-callout"><Zap size={15} /><span><b>Утренний пик на 14% выше вечернего</b><small>Рекомендуем проверить интервалы выпуска на маршрутах №17 и №12</small></span></div></article></section><section className="stands-bottom-grid"><InsightMini icon={<CalendarDays size={16} />} title="Выбранная дата»" value="Пятница, 14 ноября" caption="Сравнить с типичным пятничным профилем" /><InsightMini icon={<Route size={16} />} title="Применён фильтр»" value={route === 'all' ? 'Все маршруты' : `Маршрут №${route}`} caption="Срез используется во всех виджетах" /></section></>}

        {active === 'scenario' && <><section className="stands-metrics three-metrics"><MetricCard icon={<Users size={17} />} label="Базовый прогноз»" value={fmt(baseTotal)} note="до применения поправок" color="blue" seed={2} /><MetricCard icon={<Sparkles size={17} />} label="После поправок»" value={fmt(currentTotal)} note="сценарный прогноз" trend={(factor - 1) * 100} color="violet" seed={6} /><MetricCard icon={<Activity size={17} />} label="Изменение»" value={`${factor >= 1 ? '+' : ''}${((factor - 1) * 100).toFixed(1)}%`} note="суммарный эффект факторов" color="mint" seed={9} /></section><section className="stands-main-grid scenario-grid"><article className="stands-card factor-card"><div className="stands-card-head"><div><h2>Факторы сценария</h2><p>Меняйте значения — итог пересчитывается сразу</p></div><button className="stands-quiet-button" onClick={() => { setWeather(1); setEvent(1); setSeason(1) }}>Сбросить</button></div><FactorControl icon={<CloudRain size={16} />} title="Погодные условия»" description="Осадки и снегопад»" value={weather} onChange={setWeather} min={.8} max={1.2} step={.01} color="blue" /><FactorControl icon={<CalendarDays size={16} />} title="События и перекрытия»" description="Мероприятие вдоль маршрута»" value={event} onChange={setEvent} min={.8} max={1.25} step={.01} color="amber" /><FactorControl icon={<Sparkles size={16} />} title="Сезонность»" description="Сезонная поправка»" value={season} onChange={setSeason} min={.85} max={1.15} step={.01} color="violet" /><div className="factor-presets"><span>Быстрые сценарии</span><button onClick={() => { setWeather(.94); setEvent(1); setSeason(1); setNotice('Применён сценарий «Сильные осадки»') }}><CloudRain size={14} /> Сильные осадки</button><button onClick={() => { setWeather(1); setEvent(1.15); setSeason(1); setNotice('Применён сценарий «Мероприятие»') }}><Users size={14} /> Мероприятие</button><button onClick={() => { setWeather(1); setEvent(.8); setSeason(1); setNotice('Применён сценарий «Перекрытие»') }}><Route size={14} /> Перекрытие</button></div></article><article className="stands-card scenario-chart-card"><div className="stands-card-head"><div><h2>Влияние на прогноз</h2><p>Базовый сценарий и выбранные поправки</p></div><span className="scenario-live"><i /> LIVE</span></div><div className="scenario-result"><span>Новый прогноз</span><strong>{fmt(currentTotal)}</strong><small>{factor >= 1 ? '+' : ''}{fmt(currentTotal - baseTotal)} к базовому прогнозу</small></div><FlowChart horizon={horizon} route={route} startDate={rangeStart} /><div className="scenario-factor-line"><span>Общий коэффициент</span><b>×{factor.toFixed(2)}</b><span>Погодные данные · демонстрационные</span></div></article></section></>}

        {active === 'dispatch' && <><section className="stands-metrics four-metrics"><MetricCard icon={<Bell size={17} />} label="Сигналы внимания»" value="3»" note="1 требует решения»" color="amber" seed={5} /><MetricCard icon={<Gauge size={17} />} label="Макс. загрузка»" value="92%»" note="маршрут №17»" trend={4.2} color="violet" seed={9} /><MetricCard icon={<Clock3 size={17} />} label="До ближайшего пика»" value="35 мин»" note="ожидается в 08:00»" color="blue" seed={4} /><MetricCard icon={<ShieldCheck size={17} />} label="Покрытие прогноза»" value="10 / 10»" note="маршрутов доступны»" color="mint" seed={10} /></section><section className="dispatch-banner"><span className="dispatch-pulse"><Zap size={19} /></span><div><b>Подготовиться к утреннему пику</b><span>На маршруте №17 загрузка может превысить 90% около 08:00. Прогноз учитывает типичный профиль пятницы.</span></div><button onClick={() => { setRoute(17); setActive('routes'); setNotice('Открыта карточка маршрута №17') }}>Открыть маршрут <ArrowRight size={14} /></button></section><section className="stands-main-grid dispatch-grid"><article className="stands-card"><div className="stands-card-head"><div><h2>Поток ближайших 24 часов</h2><p>{route === 'all' ? 'Все маршруты' : `Маршрут №${route}`} · посадок в час</p></div><span className="stands-status-pill"><i /> прогноз активен</span></div><FlowChart horizon="day" route={route} startDate={rangeStart} /><div className="dispatch-timeline"><div><span>СЕЙЧАС</span><b>07:25</b></div><i /><div><span>УТРЕННИЙ ПИК</span><b>08:00–09:00</b></div><i /><div><span>ВЕЧЕРНИЙ ПИК</span><b>17:00–18:00</b></div></div></article><article className="stands-card"><div className="stands-card-head"><div><h2>Сигналы по маршрутам</h2><p>Отсортировано по срочности</p></div><span className="stands-count-badge">3</span></div><div className="dispatch-alerts"><button onClick={() => { setRoute(17); setActive('routes') }}><span className="alert-level high">ВЫСОКО</span><span><b>№17 · загрузка 92%</b><small>Пик через 35 минут · +8,4% к прошлой неделе</small></span><ArrowRight size={14} /></button><button onClick={() => { setRoute(12); setActive('routes') }}><span className="alert-level medium">СРЕДНЕ</span><span><b>№12 · рост пассажиропотока</b><small>+3,1% · вечерний пик в 18:00</small></span><ArrowRight size={14} /></button><button onClick={() => { setRoute(11); setActive('routes') }}><span className="alert-level low">НИЗКО</span><span><b>№11 · ниже базового профиля</b><small>−2,6% · без влияния на расписание</small></span><ArrowRight size={14} /></button></div></article></section></>}

        <footer className="stands-footer"><span><i /> DEMO · данные для оценки интерфейса, не для оперативных решений</span><span>Наброски UX · 5 концепций</span></footer>
      </div>
    </main>
  </div>
}

function RouteTable({ routes, onChoose, onOpenAll, expanded = false }: { routes: typeof routeData; onChoose: (id: number) => void; onOpenAll?: () => void; expanded?: boolean }) {
  return <article className={`stands-card stands-route-card ${expanded ? 'expanded' : ''}`}><div className="stands-card-head"><div><h2>{expanded ? 'Показатели по маршрутам' : 'Маршруты под наблюдением'}</h2><p>{expanded ? 'Кликните маршрут для детализации · данные демонстрационные' : 'Сводка по пассажиропотоку за выбранный период'}</p></div>{!expanded && <button className="stands-link-button" onClick={onOpenAll}>Все маршруты <ArrowRight size={14} /></button>}</div><div className="stands-route-table"><div className="stands-table-head"><span>МАРШРУТ</span><span>ПАССАЖИРОПОТОК</span><span>К ПРОШЛОЙ НЕДЕЛЕ</span><span>ЧАС ПИК</span><span>ЗАГРУЗКА</span></div>{routes.map((item, index) => <button className="stands-route-row" key={item.id} onClick={() => onChoose(item.id)}><span className="route-name-cell"><b className="route-id" style={{ '--route-color': item.color } as React.CSSProperties}>{item.id}</b><span><strong>Маршрут №{item.id}</strong><small>{item.name}</small></span></span><span className="route-volume"><b>{fmt(item.total)}</b><SmallLine seed={index + 3} color={item.color} /></span><span><Trend value={item.delta} /></span><span className="route-peak"><Clock3 size={13} /> {item.peak}</span><span className="route-load"><span className="load-track"><i style={{ width: `${item.load}%`, background: item.load > 85 ? '#f1a968' : item.color }} /></span><b>{item.load}%</b></span></button>)}</div>{!routes.length && <div className="stands-empty">Нет маршрутов по этому запросу</div>}</article>
}

function InsightMini({ icon, title, value, caption }: { icon: React.ReactNode; title: string; value: string; caption: string }) {
  return <article className="stands-card insight-mini"><span>{icon}</span><div><small>{title.replace(/»/g, '')}</small><b>{value}</b><em>{caption}</em></div><ArrowRight size={15} /></article>
}

function FactorControl({ icon, title, description, value, onChange, min, max, step, color }: { icon: React.ReactNode; title: string; description: string; value: number; onChange: (value: number) => void; min: number; max: number; step: number; color: string }) {
  return <div className="factor-control"><span className={`factor-icon ${color}`}>{icon}</span><div className="factor-main"><div className="factor-label"><span><b>{title.replace(/»/g, '')}</b><small>{description.replace(/»/g, '')}</small></span><strong>×{value.toFixed(2)}</strong></div><input type="range" min={min} max={max} step={step} value={value} style={{ '--range-progress': `${(value - min) / (max - min) * 100}%` } as React.CSSProperties} onChange={(e) => onChange(Number(e.target.value))} aria-label={title.replace(/»/g, '')} /><div className="factor-scale"><span>{min.toFixed(2)}</span><span>Базовый ×1.00</span><span>{max.toFixed(2)}</span></div></div></div>
}

export default Stands
