import {
  BarChart, Bar, XAxis, YAxis, Cell, ReferenceLine, Tooltip, ResponsiveContainer,
} from 'recharts'

const POS_FULL = {
  QB: 'Quarterback', RB: 'Running Back', WR: 'Wide Receiver', TE: 'Tight End',
  OL: 'Offensive Line', IDL: 'Interior D-Line', EDGE: 'Edge Rusher',
  LB: 'Linebacker', CB: 'Cornerback', S: 'Safety', SPEC: 'Special Teams',
}

const PAY_UP = '#1a7f37'
const VALUE = '#d4691e'

function PremiumTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div style={{ background: '#1c232d', border: '1px solid #2a313c', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
      <strong>{d.position}</strong>
      <div style={{ color: '#9aa5b1', marginTop: 2 }}>
        {d.pp >= 0 ? '+' : ''}{d.pp.toFixed(2)} pts of cap vs league avg
      </div>
    </div>
  )
}

// Diverging horizontal bar of champion premium by position — mirrors the
// Streamlit/Tableau view: green = champions pay up, orange = value.
export function ChampionPremiumChart({ data }) {
  const rows = data
    .map((d) => ({
      position: POS_FULL[d.pos_group] ?? d.pos_group,
      pp: d.premium * 100,
    }))
    .sort((a, b) => b.pp - a.pp)

  return (
    <ResponsiveContainer width="100%" height={Math.max(300, rows.length * 34 + 40)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
        <XAxis
          type="number"
          tickFormatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
          tick={{ fill: '#9aa5b1', fontSize: 12 }}
          stroke="#2a313c"
        />
        <YAxis
          type="category"
          dataKey="position"
          width={120}
          tick={{ fill: '#e6edf3', fontSize: 13 }}
          stroke="#2a313c"
        />
        <ReferenceLine x={0} stroke="#c9ced4" />
        <Tooltip content={<PremiumTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Bar dataKey="pp" radius={[0, 3, 3, 0]} label={{
          position: 'right', fill: '#9aa5b1', fontSize: 12,
          formatter: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
        }}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.pp >= 0 ? PAY_UP : VALUE} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
