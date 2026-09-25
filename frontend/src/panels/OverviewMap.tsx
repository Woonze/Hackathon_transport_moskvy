import { MapPin } from 'lucide-react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip as MapTooltip } from 'react-leaflet'
import type { Feature, FeatureCollection, LineString, MultiLineString } from 'geojson'
import 'leaflet/dist/leaflet.css'

type RouteFeature = Feature<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>
type RouteGeo = FeatureCollection<LineString | MultiLineString, { route: number; stop_count: number; stops: string[] }>

const routeColors: Record<number, string> = { 1: '#2e6bff', 5: '#f0a339', 7: '#00a78b', 11: '#8556e8', 12: '#e65f73', 17: '#62748b', 25: '#14a5c7', 26: '#dc8b23', 28: '#b15cb7', 50: '#46804c' }

export default function OverviewMap({ route, geo }: { route: number | 'all'; geo: RouteGeo }) {
  const features = (geo.features as RouteFeature[]).filter((feature) => route === 'all' || feature.properties?.route === route)
  const data = { ...geo, features } as RouteGeo

  return <article className="panel map-panel"><div className="panel-heading"><div><div className="panel-title">Маршруты на карте</div><div className="panel-subtitle">География остановок и схема движения</div></div><div className="map-badge"><MapPin size={13} /> МОСКВА</div></div><div className="map-frame"><MapContainer center={[55.7558, 37.6173]} zoom={10} scrollWheelZoom={false} className="leaflet-map"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /><GeoJSON key={`${route}-${features.length}`} data={data} style={(feature) => ({ color: routeColors[feature?.properties?.route ?? 1] ?? '#4770eb', weight: 4, opacity: 0.78, lineCap: 'round', lineJoin: 'round' })} onEachFeature={(feature, layer) => { const props = feature.properties as RouteFeature['properties']; layer.bindTooltip(`Трамвай ${props?.route ?? ''} · ${props?.stop_count ?? 0} остановок`, { sticky: true }) }} />{features.flatMap((feature, index) => (feature.geometry.type === 'LineString' ? feature.geometry.coordinates : feature.geometry.coordinates[0]).filter((_, i) => i % 2 === 0).map((coord, i) => <CircleMarker key={`${index}-${i}`} center={[coord[1], coord[0]]} radius={3.2} pathOptions={{ color: '#fff', weight: 1.4, fillColor: routeColors[feature.properties?.route ?? 1], fillOpacity: 0.96 }}><MapTooltip>{feature.properties?.stops?.[i * 2] ?? `Остановка ${i + 1}`}</MapTooltip></CircleMarker>))}</MapContainer><div className="map-legend"><span className="legend-line" /> Маршрут <span className="legend-stop" /> Остановка</div></div><div className="map-note"><span className="note-info">i</span><span>Схема построена по доступным координатам остановок из справочника. Показаны маршруты 1, 5, 7, 11 и 12.</span></div></article>
}
