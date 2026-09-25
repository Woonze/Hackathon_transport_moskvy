import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type FlowRow = { label: string; passengers: number }

export default function FlowChart({ mode, data, total, caption, format, onModeChange }: {
  mode: 'days' | 'hours'
  data: FlowRow[]
  total: string
  caption: string
  format: (value: number) => string
  onModeChange: (mode: 'days' | 'hours') => void
}) {
  return <article className="panel flow-panel"><div className="panel-heading flow-heading"><div><div className="panel-title">Динамика пассажиропотока</div><div className="panel-subtitle">{mode === 'days' ? 'Суммарный прогноз по дням месяца' : 'Почасовой прогноз на выбранную дату'}</div></div><div className="segmented"><button className={mode === 'days' ? 'active' : ''} onClick={() => onModeChange('days')}>По дням</button><button className={mode === 'hours' ? 'active' : ''} onClick={() => onModeChange('hours')}>По часам</button></div></div><div className="chart-summary"><div><strong>{total}</strong><span>{caption}</span></div><div className="chart-period"><span className="chart-key" /> Прогноз</div></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 12, right: 8, left: -14, bottom: 0 }}><defs><linearGradient id="flowGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#537dff" stopOpacity={0.2} /><stop offset="100%" stopColor="#537dff" stopOpacity={0.015} /></linearGradient></defs><CartesianGrid stroke="#edf0f6" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 11 }} interval={mode === 'days' ? 6 : 3} minTickGap={16} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#98a1b2', fontSize: 11 }} tickFormatter={(n) => n >= 1000 ? `${(n / 1000).toFixed(0)}к` : n} /><Tooltip contentStyle={{ border: '1px solid #edf0f6', borderRadius: 12, boxShadow: '0 8px 28px #26395c17', fontSize: 12 }} formatter={(value) => [`${format(Number(value))} пассажиров`, 'Прогноз']} labelStyle={{ color: '#647087', marginBottom: 4 }} /><Area type="monotone" dataKey="passengers" stroke="#4f75f3" strokeWidth={2.5} fill="url(#flowGradient)" activeDot={{ r: 5, strokeWidth: 3, stroke: '#fff' }} /></AreaChart></ResponsiveContainer></div><div className="chart-footer"><span><span className="foot-dot blue-dot" /> Средний прогноз по выбранному периоду</span><button onClick={() => onModeChange(mode === 'days' ? 'hours' : 'days')}>Подробнее <span>↗</span></button></div></article>
}
