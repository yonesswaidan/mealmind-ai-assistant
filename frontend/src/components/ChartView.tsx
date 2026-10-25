import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell as PieCell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartSpec, Cell } from '../types'
import { formatValue, isDateLike } from '../format'
import { columnLabel, displayValue, isCompact, unitFor } from '../present'

// Faste kategoriske slots fra den validerede palette; tildeles i rækkefølge, aldrig cyklet.
const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`)
const PIE_MAX = 7

const axisProps = {
  stroke: 'var(--axis)',
  tick: { fill: 'var(--text-muted)', fontSize: 12 },
  axisLine: { stroke: 'var(--axis)' },
  tickLine: false,
}

function tickFormatter(v: Cell) {
  if (typeof v === 'string') return isDateLike(v) ? v.slice(0, 10) : displayValue(v)
  return formatValue(v, true)
}

function pieData(spec: ChartSpec) {
  const key = spec.y[0]
  const rows = [...spec.data].sort((a, b) => Number(b[key] ?? 0) - Number(a[key] ?? 0))
  if (rows.length <= PIE_MAX) return rows
  const rest = rows.slice(PIE_MAX - 1).reduce((s, r) => s + Number(r[key] ?? 0), 0)
  return [...rows.slice(0, PIE_MAX - 1), { [spec.x]: 'Andet', [key]: rest }]
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: Cell; color: string }[]; label?: Cell }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label != null && <div className="chart-tooltip-label">{tickFormatter(label)}</div>}
      {payload.map((p) => (
        <div key={p.name} className="chart-tooltip-row">
          <span className="swatch" style={{ background: p.color }} />
          <span className="chart-tooltip-name">{p.name}</span>
          <span className="chart-tooltip-value">{formatValue(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

function CompactBars({ spec }: { spec: ChartSpec }) {
  const key = spec.y[0]
  const unit = unitFor(key) || unitFor(spec.y_label ?? '')
  const max = Math.max(...spec.data.map((r) => r[key] as number), 0) || 1
  return (
    <figure className="card chart-card compact-card" aria-label={spec.title}>
      <figcaption className="card-title">{spec.title}</figcaption>
      {spec.y_label && <div className="axis-caption">{spec.y_label}</div>}
      <div className="compact-bars" role="list">
        {spec.data.map((r, i) => {
          const v = r[key] as number
          const label = displayValue(r[spec.x])
          const value = `${formatValue(v)}${unit ? ` ${unit}` : ''}`
          return (
            <div key={i} className="compact-col" role="listitem" title={`${label}: ${value}`}>
              <span className="compact-label">{label}</span>
              <span className="compact-value">{value}</span>
              <span className="compact-track">
                <span className="compact-bar" style={{ height: `${Math.max(4, (v / max) * 100)}%` }} />
              </span>
            </div>
          )
        })}
      </div>
      {spec.notes.length > 0 && <div className="card-note">{spec.notes.join(' ')}</div>}
    </figure>
  )
}

export function ChartView({ spec }: { spec: ChartSpec }) {
  if (isCompact(spec)) return <CompactBars spec={spec} />
  const multi = spec.y.length > 1
  const common = { data: spec.data, margin: { top: 8, right: 16, bottom: 8, left: 8 } }
  const grid = <CartesianGrid stroke="var(--grid)" vertical={false} />
  const x = <XAxis dataKey={spec.x} {...axisProps} tickFormatter={tickFormatter} minTickGap={24} />
  const y = <YAxis {...axisProps} axisLine={false} tickFormatter={(v) => formatValue(v, true)} width={56} />
  const tooltip = <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--axis)', fill: 'var(--hover)' }} />
  const legend = multi ? <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)' }} iconType="circle" iconSize={8} /> : null

  let chart: React.ReactElement
  switch (spec.type) {
    case 'line':
      chart = (
        <LineChart {...common}>
          {grid}{x}{y}{tooltip}{legend}
          {spec.y.map((k, i) => (
            <Line key={k} dataKey={k} name={columnLabel(k)} stroke={SERIES[i]} strokeWidth={2} dot={spec.data.length <= 24 ? { r: 4, fill: SERIES[i], strokeWidth: 2, stroke: 'var(--surface-1)' } : false} activeDot={{ r: 5, fill: SERIES[i], stroke: 'var(--surface-1)', strokeWidth: 2 }} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      )
      break
    case 'area':
      chart = (
        <AreaChart {...common}>
          {grid}{x}{y}{tooltip}{legend}
          {spec.y.map((k, i) => (
            <Area key={k} dataKey={k} name={columnLabel(k)} stroke={SERIES[i]} fill={SERIES[i]} fillOpacity={spec.stacked ? 0.85 : 0.18} strokeWidth={2} stackId={spec.stacked ? 's' : undefined} connectNulls isAnimationActive={false} />
          ))}
        </AreaChart>
      )
      break
    case 'scatter':
      chart = (
        <ScatterChart {...common}>
          {grid}
          <XAxis dataKey={spec.x} type="number" name={spec.x} {...axisProps} tickFormatter={(v) => formatValue(v, true)} />
          <YAxis dataKey={spec.y[0]} type="number" name={spec.y[0]} {...axisProps} axisLine={false} tickFormatter={(v) => formatValue(v, true)} width={56} />
          <Tooltip content={<ChartTooltip />} />
          <Scatter data={spec.data} fill={SERIES[0]} stroke="var(--surface-1)" strokeWidth={2} isAnimationActive={false} />
        </ScatterChart>
      )
      break
    case 'pie': {
      const data = pieData(spec)
      chart = (
        <PieChart>
          <Tooltip content={<ChartTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)' }} iconType="circle" iconSize={8} />
          <Pie data={data} dataKey={spec.y[0]} nameKey={spec.x} innerRadius="55%" outerRadius="85%" stroke="var(--surface-1)" strokeWidth={2} isAnimationActive={false}>
            {data.map((_, i) => <PieCell key={i} fill={SERIES[i]} />)}
          </Pie>
        </PieChart>
      )
      break
    }
    default:
      chart = (
        <BarChart {...common} barCategoryGap="20%">
          {grid}{x}{y}{tooltip}{legend}
          {spec.y.map((k, i) => (
            <Bar key={k} dataKey={k} name={columnLabel(k)} fill={SERIES[i]} stackId={spec.stacked ? 's' : undefined} stroke="var(--surface-1)" strokeWidth={spec.stacked || multi ? 2 : 0} radius={spec.stacked && i < spec.y.length - 1 ? 0 : [4, 4, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      )
  }

  return (
    <figure className="card chart-card" aria-label={spec.title}>
      <figcaption className="card-title">{spec.title}</figcaption>
      {(spec.y_label || spec.x_label) && (
        <div className="axis-caption">{[spec.y_label, spec.x_label && `x: ${spec.x_label}`].filter(Boolean).join(' · ')}</div>
      )}
      <div className="chart-body">
        <ResponsiveContainer width="100%" height="100%">
          {chart}
        </ResponsiveContainer>
      </div>
      {spec.notes.length > 0 && <div className="card-note">{spec.notes.join(' ')}</div>}
    </figure>
  )
}
