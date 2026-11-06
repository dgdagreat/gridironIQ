import { POS_UNIT, UNITS, UNIT_COLOR } from '../lib/positions.js'

// Three-slice donut of cap split across offense / defense / special teams — the
// high-level balance the position bar can't show at a glance. Built as a single
// SVG ring: each unit is an arc sized by its share of the team's committed cap.
export function SpendingDonut({ positions, team }) {
  const totals = { Offense: 0, Defense: 0, 'Special teams': 0 }
  for (const p of positions) {
    totals[POS_UNIT[p.pos_group] ?? 'Special teams'] += p.cap_pct_norm || 0
  }
  const sum = UNITS.reduce((s, u) => s + totals[u], 0) || 1

  const R = 62
  const C = 2 * Math.PI * R
  let acc = 0
  const segs = UNITS.map((u) => {
    const frac = totals[u] / sum
    const seg = { u, frac, dash: frac * C, offset: -acc * C, color: UNIT_COLOR[u] }
    acc += frac
    return seg
  })

  return (
    <div className="donut">
      <svg viewBox="0 0 160 160" className="donut-svg" role="img" aria-label={`${team} cap split: offense, defense, special teams`}>
        <g transform="rotate(-90 80 80)">
          {segs.map((s) => (
            <circle key={s.u} cx="80" cy="80" r={R} fill="none" stroke={s.color}
              strokeWidth="22" strokeDasharray={`${s.dash} ${C - s.dash}`}
              strokeDashoffset={s.offset} />
          ))}
        </g>
        <text x="80" y="86" textAnchor="middle" className="donut-center">{team}</text>
      </svg>
      <div className="donut-legend">
        {segs.map((s) => (
          <span key={s.u}><i style={{ background: s.color }} />{s.u} · {(100 * s.frac).toFixed(0)}%</span>
        ))}
      </div>
    </div>
  )
}
