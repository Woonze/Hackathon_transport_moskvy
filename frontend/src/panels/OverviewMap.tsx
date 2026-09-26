import { MapPin } from 'lucide-react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip as MapTooltip } from 'react-leaflet'
import type { Feature, FeatureCollection, LineString, MultiLineString } from 'geojson'
import 'leaflet/dist/leaflet.css'

type RouteFeature = Feature<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
type RouteGeo = FeatureCollection<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>

const routeColors: Record<number, string> = { 1: '#2e6bff', 5: '#f0a339', 7: '#00a78b', 11: '#8556e8', 12: '#e65f73', 17: '#62748b', 25: '#14a5c7', 26: '#dc8b23', 28: '#b15cb7', 50: '#46804c' }
type MapMode = 'passengers' | 'overload' | 'deviation' | 'forecast'
type Metric = { value: number; delta: number }

const modeTitles: Record<MapMode, string> = {
  passengers: 'Пассажиропоток',
  overload: 'Уровень загрузки',
  deviation: 'Отклонение прогноза',
  forecast: 'Прогнозный слой',
}
const modeDescriptions: Record<MapMode, string> = {
  passengers: 'Каждый маршрут выделен собственным цветом',
  overload: 'Зелёный — низкая, оранжевый — средняя, красный — высокая загрузка',
  deviation: 'Синий — снижение, зелёный — норма, оранжевый и красный — рост к среднему',
  forecast: 'Чем толще линия, тем выше прогнозный пассажиропоток',
}

export default function OverviewMap({ route, geo, mode = 'passengers', metrics = {} }: { route: number | 'all'; geo: RouteGeo; mode?: MapMode; metrics?: Record<number, Metric> }) {
  const features = (geo.features as RouteFeature[]).filter((feature) => route === 'all' || feature.properties?.route === route)
  const data = { ...geo, features } as RouteGeo
  const maxValue = Math.max(1, ...Object.values(metrics).map((metric) => metric.value))
  const styleFor = (routeId: number) => {
    const metric = metrics[routeId] ?? { value: 0, delta: 0 }
    if (mode === 'overload') {
      const load = metric.value / maxValue
      return { color: load > 0.72 ? '#f14c5b' : load > 0.42 ? '#f59643' : '#20c889', weight: 3 + load * 4 }
    }
    if (mode === 'deviation') return { color: metric.delta >= 20 ? '#f14c5b' : metric.delta >= 5 ? '#f59643' : metric.delta < 0 ? '#36a8ff' : '#20c889', weight: 4 }
    if (mode === 'forecast') return { color: '#3c92f1', weight: 3 + metric.value / maxValue * 4 }
    return { color: routeColors[routeId] ?? '#4770eb', weight: 4 }
  }

  return <article className="panel map-panel"><div className="panel-heading"><div><div className="panel-title">Маршруты на карте</div><div className="panel-subtitle">{modeTitles[mode]}</div></div><div className="map-badge"><MapPin size={13} /> МОСКВА</div></div><div className="map-frame"><MapContainer center={[55.7558, 37.6173]} zoom={10} scrollWheelZoom={false} className="leaflet-map"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /><GeoJSON key={`${route}-${features.length}-${mode}`} data={data} style={(feature) => ({ ...styleFor(feature?.properties?.route ?? 1), opacity: 0.84, lineCap: 'round', lineJoin: 'round' })} onEachFeature={(feature, layer) => { const props = feature.properties as RouteFeature['properties']; const metric = metrics[props?.route]; layer.bindTooltip(`Трамвай ${props?.route ?? ''} · ${props?.stop_count ?? 0} остановок${metric ? ` · ${mode === 'deviation' ? `${metric.delta >= 0 ? '+' : ''}${metric.delta.toFixed(1)}%` : `${Math.round(metric.value).toLocaleString('ru-RU')} посадок`}` : ''}`, { sticky: true }) }} />{features.flatMap((feature, index) => (feature.geometry.type === 'LineString' ? feature.geometry.coordinates : feature.geometry.coordinates[0]).filter((_, i) => i % 2 === 0).map((coord, i) => <CircleMarker key={`${index}-${i}`} center={[coord[1], coord[0]]} radius={3.2} pathOptions={{ color: '#fff', weight: 1.4, fillColor: styleFor(feature.properties?.route ?? 1).color, fillOpacity: 0.96 }}><MapTooltip>{feature.properties?.stops?.[i * 2] ?? `Остановка ${i + 1}`}</MapTooltip></CircleMarker>))}</MapContainer><div className="map-mode-info"><b>{modeTitles[mode]}</b><span>{modeDescriptions[mode]}</span></div><div className={`map-legend mode-${mode}`}><span className="legend-line" /> {modeTitles[mode]} <span className="legend-stop" /> Остановка</div></div><div className="map-note"><span className="note-info">i</span><span>Схема построена по доступным координатам остановок из справочника.</span></div></article>
}
