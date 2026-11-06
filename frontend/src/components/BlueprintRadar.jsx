import { POS_ORDER } from '../lib/positions.js'

// Radar overlay: the team's normalized cap share at each position laid over the
// Super Bowl champion average, so the roster's spending *shape* reads against the
// title blueprint. The team polygon (green) bulging past the champion outline
// (grey, dotted) = over-invested there; caving inside it = under-invested.
export function BlueprintRadar({ positions, premium, team, season }) {
  const champ = new Map(premium.map((d) => [d.pos_group, d.champion_avg]))
  const teamShare = new Map(positions.map((d) => [d.pos_group, d.cap_pct_norm]))
  const order = POS_ORDER.filter((p) => champ.has(p) || teamShare.has(p))
  const n = order.length
  if (!n) return null

  const champV = order.map((p) => (champ.get(p) ?? 0) * 100)
  const teamV = order.map((p) => (teamShare.get(p) ?? 0) * 100)
  const rmax = (Math.max(...champV, ...teamV) || 1) * 1.12

  const CX = 150, CY = 150, R = 108
  const at = (val, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n
    const r = (val / rmax) * R
    return [CX + r * Math.cos(ang), CY + r * Math.sin(ang)]
  }
  const poly = (vals) => vals.map((v, i) => at(v, i).join(',')).join(' ')

  return (
    <div className="radar">
      <svg viewBox="0 0 300 300" className="radar-svg" role="img" aria-label={`${team} cap shape vs the Super Bowl champion blueprint`}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <polygon key={f} points={order.map((_, i) => at(rmax * f, i).join(',')).join(' ')}
            fill="none" stroke="var(--line)" strokeWidth="1" />
        ))}
        {order.map((p, i) => {
          const [x, y] = at(rmax, i)
          const [lx, ly] = at(rmax * 1.17, i)
          return (
            <g key={p}>
              <line x1={CX} y1={CY} x2={x} y2={y} stroke="var(--line)" strokeWidth="1" />
              <text x={lx} y={ly} className="radar-label" textAnchor="middle" dominantBaseline="middle">{p}</text>
            </g>
          )
        })}
        <polygon points={poly(champV)} fill="rgba(150,157,176,0.12)" stroke="var(--ink-faint)" strokeWidth="1.5" strokeDasharray="4 3" />
        <polygon points={poly(teamV)} fill="rgba(37,211,102,0.18)" stroke="var(--pay)" strokeWidth="2" />
      </svg>
      <div className="radar-legend">
        <span><i className="dash" />SB champion avg</span>
        <span><i style={{ background: 'var(--pay)' }} />{team} {season}</span>
      </div>
    </div>
  )
}
