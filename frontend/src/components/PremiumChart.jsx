import { signedPct } from '../lib/format.js'

const POS_FULL = {
  QB: 'Quarterback', RB: 'Running Back', WR: 'Wide Receiver', TE: 'Tight End',
  OL: 'Offensive Line', T: 'Offensive Tackle', G: 'Offensive Guard', C: 'Center',
  IDL: 'Interior D-Line', EDGE: 'Edge Rusher', LB: 'Linebacker',
  CB: 'Cornerback', S: 'Safety', SPEC: 'Special Teams',
}

// Diverging horizontal bars of champion premium (champion cap share minus the
// league average), built from scratch so the look is ours. Right/green = pay up.
export function PremiumChart({ data }) {
  const rows = data
    .map((d) => ({
      pos: POS_FULL[d.pos_group] ?? d.pos_group,
      pp: d.premium * 100,
      champ: (d.champion_avg ?? 0) * 100,
      league: (d.league_avg ?? 0) * 100,
    }))
    .sort((a, b) => b.pp - a.pp)

  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.pp)), 0.01)
  const barW = (pp) => (Math.abs(pp) / maxAbs) * 36 // % of the half-track; leaves room for the end label

  return (
    <div>
      <div className="premium">
        {rows.map((r) => {
          const w = barW(r.pp)
          const pay = r.pp >= 0
          return (
            <div
              className="premium-row"
              key={r.pos}
              title={`${r.pos}: champions spend ${r.champ.toFixed(1)}% of the cap here vs ${r.league.toFixed(1)}% league average (${r.pp >= 0 ? '+' : ''}${r.pp.toFixed(2)} pts)`}
            >
              <div className="pos">{r.pos}</div>
              <div className="premium-track">
                <div
                  className={`premium-bar ${pay ? 'pay' : 'value'}`}
                  style={pay ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
                />
                <div
                  className="premium-val"
                  style={pay
                    ? { left: `calc(50% + ${w}% + 7px)` }
                    : { right: `calc(50% + ${w}% + 7px)`, textAlign: 'right' }}
                >
                  {signedPct(r.pp / 100)}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="premium-axis">
        <div />
        <div className="scale">
          <span>← win spending less</span>
          <span>league avg</span>
          <span>pay up to win →</span>
        </div>
      </div>
    </div>
  )
}
