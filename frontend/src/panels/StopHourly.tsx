import { Area, AreaChart, CartesianGrid, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type HourRow = { hour: number; passengers: number }

const pad = (hour: number) => `${String(hour).padStart(2, '0')}:00`
const percent = (value: number) => `${(value * 100).toFixed(1).replace('.', ',')} %`

/** Посадки на остановке за сутки: кривая по часам, пиковые часы и сводка. Значения — оценка модели, не измерение. */
export default function StopHourly({ hourly, share, dateText, weekTotal, monthTotal, format }: {
  hourly: HourRow[]
  share: number
  dateText: string
  weekTotal: number
  monthTotal: number
  format: (value: number) => string
}) {
  const byHour = new Map(hourly.map((item) => [item.hour, item.passengers]))
  const rows = Array.from({ length: 24 }, (_, hour) => ({ hour, label: pad(hour), passengers: byHour.get(hour) ?? 0 }))
  const total = rows.reduce((sum, item) => sum + item.passengers, 0)
  const activeHours = rows.filter((item) => item.passengers >= total * 0.01)
  const average = activeHours.length ? Math.round(total / activeHours.length) : 0
  const peaks = rows.filter((item) => item.passengers > 0).sort((a, b) => b.passengers - a.passengers).slice(0, 3)
  const peakShare = total > 0 ? peaks.reduce((sum, item) => sum + item.passengers, 0) / total : 0
  const best = peaks[0]
  const strongest = (from: number, to: number) => rows.filter((item) => item.hour >= from && item.hour <= to).reduce((top, item) => item.passengers > top.passengers ? item : top, { hour: from, label: pad(from), passengers: 0 })
  const morning = strongest(5, 11)
  const evening = strongest(15, 21)
  const peakLabels = new Set(peaks.map((item) => item.label))

  return <div className="stop-hourly">
    <div className="stop-kpis">
      <div><span>Посадок за день</span><b>{format(total)}</b><small>{dateText}</small></div>
      <div><span>Главный пик</span><b>{best ? pad(best.hour) : '—'}</b><small>{best ? `${format(best.passengers)} посадок` : 'нет данных'}</small></div>
      <div><span>Среднее за час</span><b>{format(average)}</b><small>в часы движения</small></div>
      <div><span>Доля потока маршрута</span><b>{percent(share)}</b><small>от посадок маршрута за день</small></div>
    </div>

    <h3>Загрузка остановки по часам<small>посадок в час, оценка модели</small></h3>
    <div className="stop-curve">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 18, right: 10, left: -14, bottom: 0 }}>
          <defs><linearGradient id="stopGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f05262" stopOpacity={0.35} /><stop offset="100%" stopColor="#f05262" stopOpacity={0.01} /></linearGradient></defs>
          <CartesianGrid stroke="#1b2b3b" vertical={false} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#66798f', fontSize: 10 }} interval={3} />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: '#66798f', fontSize: 10 }} tickFormatter={(n) => n >= 1000 ? `${(n / 1000).toFixed(1).replace('.0', '')}к` : n} width={38} />
          <Tooltip contentStyle={{ border: '1px solid #26394d', background: '#0b1722', color: '#dce6f5', borderRadius: 8, fontSize: 11 }} labelStyle={{ color: '#8fa0b4', marginBottom: 4 }} formatter={(value) => [`${format(Number(value))} посадок · ${total ? percent(Number(value) / total) : '0 %'} суток`, 'Оценка']} />
          <Area type="monotone" dataKey="passengers" stroke="#f05262" strokeWidth={2.5} fill="url(#stopGradient)" activeDot={{ r: 5, strokeWidth: 3, stroke: '#0b1722' }} />
          {rows.filter((item) => peakLabels.has(item.label)).map((item) => <ReferenceDot key={item.label} x={item.label} y={item.passengers} r={4} fill="#ffd3d8" stroke="#0b1722" strokeWidth={2} label={{ value: format(item.passengers), position: 'top', fill: '#ffd3d8', fontSize: 10, fontWeight: 700 }} />)}
        </AreaChart>
      </ResponsiveContainer>
    </div>

    <h3>Часы пик{peaks.length > 0 && <small>{percent(peakShare)} суток приходится на 3 часа</small>}</h3>
    <div className="stop-peaks">
      {peaks.length === 0 && <div className="stop-peak-empty">Для выбранного дня посадок нет.</div>}
      {peaks.map((item, index) => <div key={item.hour}>
        <em>{index + 1}</em><b>{pad(item.hour)}–{pad((item.hour + 1) % 24)}</b>
        <i><u style={{ width: `${Math.round(item.passengers / Math.max(best.passengers, 1) * 100)}%` }} /></i>
        <span>{format(item.passengers)}</span><small>{percent(item.passengers / Math.max(total, 1))}</small>
      </div>)}
    </div>
    <div className="stop-split"><span>Утренний пик <b>{morning.passengers ? `${morning.label} · ${format(morning.passengers)}` : '—'}</b></span><span>Вечерний пик <b>{evening.passengers ? `${evening.label} · ${format(evening.passengers)}` : '—'}</b></span></div>

    <div className="stop-period"><span>Ближайшие 7 дней<b>{format(weekTotal)}</b></span><span>Месяц<b>{format(monthTotal)}</b></span></div>
    <p className="stop-note">Оценка модели: посадки маршрута распределены по остановкам по весам (начальная остановка, узел, конечная), это не измерение по остановкам.</p>
  </div>
}
