import { Fragment, useEffect } from 'react'
import { MapPin } from 'lucide-react'
import { CircleMarker, GeoJSON, MapContainer, Pane, TileLayer, Tooltip as MapTooltip, useMap, useMapEvents } from 'react-leaflet'
import type { Feature, FeatureCollection, LineString, MultiLineString } from 'geojson'
import 'leaflet/dist/leaflet.css'

type RouteFeature = Feature<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
type RouteGeo = FeatureCollection<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
export type MapStop = { route: number; direction: number; sequence: number; stop_id: string; name: string; lat: number; lon: number; district: string | null; is_hub: boolean; boarding_share: number }

const routeColors: Record<number, string> = { 1: '#2e6bff', 5: '#f0a339', 7: '#00a78b', 11: '#8556e8', 12: '#e65f73', 17: '#62748b', 25: '#14a5c7', 26: '#dc8b23', 28: '#b15cb7', 50: '#46804c' }
type MapMode = 'passengers' | 'overload' | 'deviation' | 'forecast'
type Metric = { value: number; delta: number }

const modeTitles: Record<MapMode, string> = {
  passengers: 'Пассажиропоток',
  overload: 'Уровень загрузки',
  deviation: 'Отклонение прогноза',
  forecast: 'Прогнозный слой',
}
const stopGroupKey = (stop: MapStop) => `${stop.route}|${stop.name.trim().toLocaleLowerCase('ru-RU')}`

function StopPicker({ stops, onSelect }: { stops: MapStop[]; onSelect?: (stop: MapStop) => void }) {
  const map = useMapEvents({
    click: (event) => {
      if (!onSelect || !stops.length) return
      const nearest = stops.reduce<{ stop: MapStop; distance: number } | null>((best, stop) => {
        const distance = map.distance(event.latlng, [stop.lat, stop.lon])
        return !best || distance < best.distance ? { stop, distance } : best
      }, null)
      if (nearest && nearest.distance <= 700) onSelect(nearest.stop)
    },
  })
  return null
}

function MapViewport({ route, points }: { route: number | 'all'; points: [number, number][] }) {
  const map = useMap()
  const signature = `${route}-${points.length}`
  useEffect(() => {
    map.invalidateSize()
    if (route === 'all') map.setView([55.7558, 37.6173], 10, { animate: true })
    else if (points.length) map.fitBounds(points, { padding: [42, 42], maxZoom: 13, animate: true })
  }, [map, signature]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function OverviewMap({ route, geo, mode = 'passengers', metrics = {}, stops = [], selectedStop, onStopSelect, onRouteSelect }: { route: number | 'all'; geo: RouteGeo; mode?: MapMode; metrics?: Record<number, Metric>; stops?: MapStop[]; selectedStop?: MapStop | null; onStopSelect?: (stop: MapStop) => void; onRouteSelect?: (route: number) => void }) {
  const features = (geo.features as RouteFeature[]).filter((feature) => route === 'all' || feature.properties?.route === route)
  const data = { ...geo, features } as RouteGeo
  const visibleStops = stops.filter((stop) => route === 'all' || stop.route === route)
  const stopByRouteAndName = new Map<string, MapStop>()
  visibleStops.forEach((stop) => {
    const key = stopGroupKey(stop)
    const current = stopByRouteAndName.get(key)
    if (!current || stop.boarding_share > current.boarding_share) stopByRouteAndName.set(key, stop)
  })
  const displayStops = [...stopByRouteAndName.values()]
  const featurePoints = features.flatMap((feature) => feature.geometry.type === 'LineString'
    ? feature.geometry.coordinates.map((coord) => [coord[1], coord[0]] as [number, number])
    : feature.geometry.coordinates.flatMap((line) => line.map((coord) => [coord[1], coord[0]] as [number, number])))
  const fitPoints = displayStops.length ? displayStops.map((stop) => [stop.lat, stop.lon] as [number, number]) : featurePoints
  const selectedStopKey = selectedStop ? stopGroupKey(selectedStop) : ''
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
  const outlineFor = (routeId: number) => {
    const delta = metrics[routeId]?.delta ?? 0
    if (delta >= 8) return '#e33f50'
    if (delta >= 2) return '#18a976'
    if (delta < 0) return '#ed8b2e'
    return null
  }

  return <article className="panel map-panel"><div className="panel-heading"><div><div className="panel-title">Маршруты на карте</div><div className="panel-subtitle">{modeTitles[mode]}</div></div><div className="map-badge"><MapPin size={13} /> МОСКВА</div></div><div className="map-frame"><MapContainer center={[55.7558, 37.6173]} zoom={10} scrollWheelZoom={false} className="leaflet-map"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /><MapViewport route={route} points={fitPoints} /><Pane name="route-lines" style={{ zIndex: 410 }}><GeoJSON key={`outline-${route}-${features.length}-${mode}`} data={data} interactive={false} style={(feature) => { const routeId = feature?.properties?.route ?? 1; const style = styleFor(routeId); const color = outlineFor(routeId); return { color: color ?? 'transparent', weight: style.weight + 2, opacity: color ? 0.9 : 0, lineCap: 'round', lineJoin: 'round' } }} /><GeoJSON key={`route-${route}-${features.length}-${mode}`} data={data} style={(feature) => ({ ...styleFor(feature?.properties?.route ?? 1), opacity: 0.94, lineCap: 'round', lineJoin: 'round', cursor: metrics[feature?.properties?.route ?? 1] ? 'pointer' : 'default' })} onEachFeature={(feature, layer) => { const props = feature.properties as RouteFeature['properties']; const routeId = props?.route; const metric = metrics[routeId]; layer.bindTooltip(`Трамвай ${routeId ?? ''} · ${props?.stop_count ?? 0} остановок${metric ? ` · ${mode === 'deviation' ? `${metric.delta >= 0 ? '+' : ''}${metric.delta.toFixed(1)}%` : `${Math.round(metric.value).toLocaleString('ru-RU')} посадок`} · нажмите для анализа` : ''}`, { sticky: true }); if (metric) layer.on('click', () => onRouteSelect?.(routeId)) }} /></Pane><StopPicker stops={displayStops} onSelect={onStopSelect} /><Pane name="stop-markers" style={{ zIndex: 430 }}>{displayStops.map((stop) => { const groupKey = stopGroupKey(stop); const active = selectedStop ? stopGroupKey(selectedStop) === groupKey : false; const color = styleFor(stop.route).color; const directions = [...new Set(visibleStops.filter((item) => stopGroupKey(item) === groupKey).map((item) => item.direction + 1))].sort(); return <Fragment key={groupKey}><CircleMarker center={[stop.lat, stop.lon]} radius={10} pathOptions={{ color: 'transparent', weight: 0, fillColor: 'transparent', fillOpacity: 0 }} bubblingMouseEvents={false} eventHandlers={{ click: () => onStopSelect?.(stop) }}><MapTooltip><b>{stop.name}</b><br />Маршрут {stop.route} · {directions.length > 1 ? `направления ${directions.join(' и ')}` : `направление ${directions[0] ?? stop.direction + 1}`}<br />Нажмите, чтобы открыть остановку</MapTooltip></CircleMarker><CircleMarker center={[stop.lat, stop.lon]} radius={route === 'all' ? stop.is_hub ? 3.2 : 2.7 : stop.is_hub ? 3.8 : 3.3} interactive={false} pathOptions={{ color: active ? '#ffffff' : route === 'all' ? '#06121c' : '#d7e8f8', weight: active ? 1.6 : route === 'all' ? 1.2 : 1.2, fillColor: active ? '#ff5265' : color, fillOpacity: 1 }} /></Fragment> })}</Pane></MapContainer><label className="map-stop-picker"><span>Остановка</span><select aria-label="Выбрать остановку на карте" value={selectedStopKey} onChange={(event) => { const stop = displayStops.find((item) => stopGroupKey(item) === event.target.value); if (stop) onStopSelect?.(stop) }}><option value="">Выберите остановку…</option>{displayStops.map((stop) => { const key = stopGroupKey(stop); return <option key={key} value={key}>№{stop.route} · {stop.name}</option> })}</select></label><div className="map-status-legend"><span><i className="below" />Ниже нормы</span><span><i className="better" />Лучше</span><span><i className="critical" />Критично</span></div><div className={`map-legend mode-${mode}`}><span className="legend-line" /> {modeTitles[mode]} <span className="legend-stop" /> Остановка</div></div><div className="map-note"><span className="note-info">i</span><span>Нажмите на линию маршрута или остановку, чтобы открыть анализ.</span></div></article>
}
