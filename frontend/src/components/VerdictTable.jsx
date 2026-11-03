import { signedPct, num } from '../lib/format.js'

const POS_FULL = {
  QB: 'Quarterback', RB: 'Running Back', WR: 'Wide Receiver', TE: 'Tight End',
  OL: 'Offensive Line', T: 'Offensive Tackle', G: 'Offensive Guard', C: 'Center',
  IDL: 'Interior D-Line', EDGE: 'Edge Rusher', LB: 'Linebacker',
  CB: 'Cornerback', S: 'Safety', SPEC: 'Special Teams',
}

function pill(v) {
  if (v.startsWith('underpaid')) return <span className="pill pay">worth paying up</span>
  if (v.startsWith('overpaid')) return <span className="pill value">overpaid</span>
  return <span className="pill fair">fairly paid</span>
}

export function VerdictTable({ data }) {
  const rows = data.filter((r) => r.champion_premium != null)
  return (
    <div className="verdict">
      {rows.map((r) => (
        <div className="verdict-row" key={r.pos_group}>
          <div className="name">{POS_FULL[r.pos_group] ?? r.pos_group}</div>
          <div className="metric">{signedPct(r.champion_premium)} · r={num(r.corr_win, 2)}</div>
          {pill(r.verdict)}
        </div>
      ))}
    </div>
  )
}
