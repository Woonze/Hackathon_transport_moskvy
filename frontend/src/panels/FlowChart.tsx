import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type FlowRow = { label: string; passengers: number }
export type ForecastPeriod = 'day' | 'week' | 'month'

const PERIOD_SUBTITLES: Record<ForecastPeriod, string> = {
  day: 'Прогноз на сутки с разбивкой по часам',
  week: 'Прогноз на неделю с разбивкой по дням',
  month: 'Прогноз на месяц с разбивкой по дням',
}

export default function FlowChart({ mode, data, total, caption, format, onModeChange }: {
  mode: ForecastPeriod
  data: FlowRow[]
  total: string
  caption: string
  format: (value: number) => string
  onModeChange: (mode: ForecastPeriod) => void
}) {
  return <article className="panel flow-panel"><div className="panel-heading flow-heading"><div><div className="panel-title">Прогноз пассажиропотока</div><div className="panel-subtitle">{PERIOD_SUBTITLES[mode]}</div></div><div className="segmented period-segmented" aria-label="Горизонт прогноза"><button aria-pressed={mode === 'day'} className={mode === 'day' ? 'active' : ''} onClick={() => onModeChange('day')}>Сегодня</button><button aria-pressed={mode === 'week'} className={mode === 'week' ? 'active' : ''} onClick={() => onModeChange('week')}>Неделя</button><button aria-pressed={mode === 'month'} className={mode === 'month' ? 'active' : ''} onClick={() => onModeChange('month')}>Месяц</button></div></div><div className="chart-summary"><div><strong>{total}</strong><span>{caption}</span></div><div className="chart-period"><span className="chart-key" /> Прогноз</div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 12, right: 8, left: -14, bottom: 0 }}><defs><linearGradient id="flowGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f05262" stopOpacity={0.35} /><stop offset="100%" stopColor="#f05262" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="#1b2b3b" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#66798f', fontSize: 11 }} interval={mode === 'month' ? 6 : mode === 'day' ? 3 : 0} minTickGap={16} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#66798f', fontSize: 11 }} tickFormatter={(n) => n >= 1000 ? `${(n / 1000).toFixed(0)}к` : n} /><Tooltip contentStyle={{ border: '1px solid #26394d', background: '#0b1722', color: '#dce6f5', borderRadius: 8, fontSize: 11 }} formatter={(value) => [`${format(Number(value))} пассажиров`, 'Прогноз']} labelStyle={{ color: '#8fa0b4', marginBottom: 4 }} /><Area type="monotone" dataKey="passengers" stroke="#f05262" strokeWidth={2.5} fill="url(#flowGradient)" activeDot={{ r: 5, strokeWidth: 3, stroke: '#0b1722' }} /></AreaChart></ResponsiveContainer></div><div className="chart-footer"><span><span className="foot-dot blue-dot" /> {mode === 'day' ? 'Почасовая детализация' : 'Дневная детализация'}</span><span className="chart-granularity">{data.length} точек</span></div></article>
}
