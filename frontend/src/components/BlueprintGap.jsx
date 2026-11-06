import { POS_FULL } from '../lib/positions.js'

// Diverging bar: the team's normalized cap share at each position minus the
// Super Bowl champion average there — how far above/below the title blueprint
// this roster sits, position by position. Blue = over-invested vs champions,
// amber = under-invested; the center line is the blueprint. Reuses the premium
// chart's track so it reads as the same visual language.
export function BlueprintGap({ positions, premium }) {
  const champ = new Map(premium.map((d) => [d.pos_group, d.champion_avg]))
  const rows = positions
    .filter((p) => champ.has(p.pos_group))
    .map((p) => ({
      pos: POS_FULL[p.pos_group] ?? p.pos_group,
      delta: ((p.cap_pct_norm || 0) - (champ.get(p.pos_group) || 0)) * 100, // percentage points
    }))
    .sort((a, b) => b.delta - a.delta)

  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.delta)), 0.5)
  const barW = (d) => (Math.abs(d) / maxAbs) * 40

  return (
    <div>
      <div className="premium">
        {rows.map((r) => {
          const w = barW(r.delta)
          const over = r.delta >= 0
          return (
            <div className="premium-row" key={r.pos}
              title={`${r.pos}: ${r.delta >= 0 ? '+' : ''}${r.delta.toFixed(1)} pts vs the champion blueprint`}>
              <div className="pos">{r.pos}</div>
              <div className="premium-track">
                <div className="premium-bar" style={over
                  ? { left: '50%', width: `${w}%`, background: 'var(--accent)', transformOrigin: 'left center' }
                  : { right: '50%', width: `${w}%`, background: 'var(--value)', transformOrigin: 'right center' }} />
                <div className="premium-val" style={over
                  ? { left: `calc(50% + ${w}% + 7px)` }
                  : { right: `calc(50% + ${w}% + 7px)`, textAlign: 'right' }}>
                  {r.delta >= 0 ? '+' : ''}{r.delta.toFixed(1)}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="premium-axis">
        <div />
        <div className="scale">
          <span>← under the blueprint</span>
          <span>on blueprint</span>
          <span>over-invested →</span>
        </div>
      </div>
    </div>
  )
}
